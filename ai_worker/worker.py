"""Persistent local inference worker for LiveSub.

stdin/stdout carry versioned NDJSON. stderr is reserved for diagnostics so a
log line can never corrupt the protocol. Audio is 16 kHz mono signed-16 PCM.
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import queue
import re
import site
import sys
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np

# Rust reads NDJSON as UTF-8. A GUI/embedded Python child on Windows otherwise
# inherits a legacy ANSI code page, which makes final Russian/Japanese/Hindi
# source transcripts fail while ASCII-only partial translations appear healthy.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="strict", line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace", line_buffering=True)

_WORKER_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
_APPLICATION_DIRECTORY = os.path.dirname(_WORKER_DIRECTORY)
for _import_root in (_APPLICATION_DIRECTORY, _WORKER_DIRECTORY):
    if _import_root not in sys.path:
        sys.path.insert(0, _import_root)

try:
    from ai_worker.language_id import LanguageEvidenceAccumulator
    from ai_worker.translation.consistency import (
        SessionGlossary,
        TerminologyEngine,
        TranslationMemory,
    )
    from ai_worker.translation.quality import check_translation_quality
except ModuleNotFoundError:
    # Packaged execution launches this file directly, making ai_worker itself
    # the import root.
    from language_id import LanguageEvidenceAccumulator
    from translation.consistency import SessionGlossary, TerminologyEngine, TranslationMemory
    from translation.quality import check_translation_quality

PROTOCOL_VERSION = 1
SAMPLE_RATE = 16_000
VAD_FRAME_SAMPLES = 512
VAD_CONTEXT_SAMPLES = 64
DIRECT_TRANSLATION_MAX_NEW_TOKENS = 128
SOURCE_TRANSCRIPTION_MAX_NEW_TOKENS = 128
_CUDA_DLL_HANDLES: list[Any] = []


def configure_cuda_dll_paths() -> list[str]:
    """Expose CUDA DLLs installed by NVIDIA Python wheels on Windows.

    Python 3.8+ no longer searches arbitrary PATH entries for extension
    dependencies, so os.add_dll_directory handles must stay alive for the
    process lifetime. System CUDA installations continue to work unchanged.
    """
    if os.name != "nt":
        return []
    roots = [*site.getsitepackages(), site.getusersitepackages()]
    directories: list[str] = []
    for root in roots:
        for relative in (
            ("nvidia", "cublas", "bin"),
            ("nvidia", "cudnn", "bin"),
            ("nvidia", "cublas", "lib"),
            ("nvidia", "cudnn", "lib"),
        ):
            candidate = os.path.join(root, *relative)
            if os.path.isdir(candidate) and candidate not in directories:
                directories.append(candidate)
                _CUDA_DLL_HANDLES.append(os.add_dll_directory(candidate))
    if directories:
        os.environ["PATH"] = os.pathsep.join((*directories, os.environ.get("PATH", "")))
    return directories


def resolve_local_model(model_name: str, model_dir: str) -> str | None:
    """Return a complete Hugging Face cache snapshot when bundled locally."""
    repository = f"models--Systran--faster-whisper-{model_name}"
    repository_dir = os.path.join(model_dir, repository)
    reference = os.path.join(repository_dir, "refs", "main")
    try:
        with open(reference, encoding="utf-8") as handle:
            revision = handle.read().strip()
    except OSError:
        return None
    snapshot = os.path.join(repository_dir, "snapshots", revision)
    required = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")
    if all(os.path.isfile(os.path.join(snapshot, name)) for name in required):
        return snapshot
    return None


def monotonic_ms() -> int:
    return time.monotonic_ns() // 1_000_000


class Emitter:
    def __init__(self) -> None:
        self._lock = threading.Lock()

    def send(self, event_type: str, **fields: Any) -> None:
        message = {
            "type": event_type,
            "protocol": PROTOCOL_VERSION,
            "emitted_ms": monotonic_ms(),
            **fields,
        }
        encoded = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            sys.stdout.write(encoded + "\n")
            sys.stdout.flush()


@dataclass(frozen=True)
class WorkerConfig:
    preset: str = "balanced"
    model: str | None = None
    device: str = "auto"
    compute_type: str = "auto"
    model_dir: str = "models"
    # Consumer/runtime execution must only use registry-verified local models.
    # Development tools may opt in explicitly when staging a new candidate.
    allow_model_download: bool = False
    vad_threshold: float = 0.50
    vad_end_ms: int = 450
    pre_roll_ms: int = 400
    partial_interval_ms: int = 800
    # A stable language is a session hint, not a permanent lock. After a real
    # pause the next source must be detected from its own audio.
    language_reset_silence_seconds: float = 12.0
    # VAD may stay open across fast narration or background music. Capping the
    # decoder window keeps finalization latency bounded on CPU while the next
    # segment immediately resumes with its own pre-roll.
    max_utterance_seconds: float = 8.0
    source_language: str | None = None

    @staticmethod
    def from_message(message: dict[str, Any]) -> "WorkerConfig":
        known = {field.name for field in WorkerConfig.__dataclass_fields__.values()}
        values = {key: value for key, value in message.items() if key in known}
        return WorkerConfig(**values)

    @property
    def selected_model(self) -> str:
        if self.model:
            return self.model
        return {"fast": "base", "balanced": "small", "accurate": "medium"}.get(
            self.preset.lower(), "small"
        )


@dataclass
class InferenceJob:
    segment_id: int
    revision: int
    audio: np.ndarray
    audio_start_ms: int
    audio_end_ms: int
    audio_capture_end_unix_ms: int
    is_final: bool


@dataclass
class AudioChunk:
    audio: np.ndarray
    capture_end_unix_ms: int


class StreamingSileroVad:
    """Stateful Silero runner for the shipped graph or a pinned A/B candidate."""

    def __init__(self, model_path: str | os.PathLike[str] | None = None) -> None:
        if model_path is None:
            from faster_whisper.vad import get_vad_model

            self._session = get_vad_model().session
        else:
            import onnxruntime

            candidate = os.fspath(model_path)
            if not os.path.isfile(candidate):
                raise FileNotFoundError(f"VAD model does not exist: {candidate}")
            self._session = onnxruntime.InferenceSession(
                candidate,
                providers=["CPUExecutionProvider"],
            )
        input_names = {item.name for item in self._session.get_inputs()}
        self._interface = (
            "state_sr" if {"input", "state", "sr"} <= input_names else "legacy_hc"
        )
        if self._interface == "legacy_hc" and not {"input", "h", "c"} <= input_names:
            raise ValueError(f"unsupported Silero VAD inputs: {sorted(input_names)}")
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((VAD_CONTEXT_SAMPLES,), dtype=np.float32)
        self._pending = np.empty((0,), dtype=np.float32)

    def reset(self) -> None:
        self._h.fill(0)
        self._c.fill(0)
        self._state.fill(0)
        self._context.fill(0)
        self._pending = np.empty((0,), dtype=np.float32)

    def feed(self, audio: np.ndarray) -> list[tuple[np.ndarray, float]]:
        self._pending = np.concatenate((self._pending, audio.astype(np.float32, copy=False)))
        results: list[tuple[np.ndarray, float]] = []
        while self._pending.size >= VAD_FRAME_SAMPLES:
            frame = self._pending[:VAD_FRAME_SAMPLES]
            self._pending = self._pending[VAD_FRAME_SAMPLES:]
            if self._interface == "state_sr":
                model_input = np.concatenate((self._context, frame))[None, :]
                speech_probs, self._state = self._session.run(
                    None,
                    {
                        "input": model_input,
                        "state": self._state,
                        "sr": np.asarray(SAMPLE_RATE, dtype=np.int64),
                    },
                )
                self._context = frame[-VAD_CONTEXT_SAMPLES:].copy()
            else:
                model_input = np.concatenate((self._context, frame))[None, :]
                speech_probs, self._h, self._c = self._session.run(
                    None, {"input": model_input, "h": self._h, "c": self._c}
                )
                self._context = frame[-VAD_CONTEXT_SAMPLES:].copy()
            results.append((frame, float(np.asarray(speech_probs).reshape(-1)[0])))
        return results


class LatestJobQueue:
    """Bounded ASR queue where a final job can evict stale partial work."""

    def __init__(self, capacity: int = 2) -> None:
        self._items: deque[InferenceJob] = deque()
        self._capacity = capacity
        self._condition = threading.Condition()
        self._closed = False

    def put(self, job: InferenceJob) -> bool:
        dropped = False
        with self._condition:
            if self._closed:
                return False
            if job.is_final:
                while len(self._items) >= self._capacity:
                    partial_index = next(
                        (i for i, item in enumerate(self._items) if not item.is_final), None
                    )
                    if partial_index is None:
                        self._items.popleft()
                    else:
                        del self._items[partial_index]
                    dropped = True
            else:
                for index in range(len(self._items) - 1, -1, -1):
                    item = self._items[index]
                    if item.segment_id == job.segment_id and not item.is_final:
                        del self._items[index]
                        dropped = True
                if len(self._items) >= self._capacity:
                    return False
            self._items.append(job)
            self._condition.notify()
        return not dropped

    def get(self) -> InferenceJob | None:
        with self._condition:
            self._condition.wait_for(lambda: self._items or self._closed)
            if self._items:
                return self._items.popleft()
            return None

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()


class AsrLoop:
    def __init__(self, config: WorkerConfig, jobs: LatestJobQueue, emitter: Emitter) -> None:
        self.config = config
        self.jobs = jobs
        self.emitter = emitter
        self._model: Any = None
        self._backend = "unloaded"
        self._context = ""
        self._source_context: dict[str, str] = {}
        self._recent_final_audio = np.empty((0,), dtype=np.float32)
        self._language_lock = LanguageEvidenceAccumulator()
        self._last_seen_segment_id: int | None = None
        self._last_final_capture_end_unix_ms: int | None = None
        self._recent_outputs: deque[str] = deque(maxlen=3)
        self._terminology = TerminologyEngine()
        self._session_glossary = SessionGlossary()
        self._translation_memory = TranslationMemory()

    def _load_model(self) -> None:
        model_name = self.config.selected_model
        os.makedirs(self.config.model_dir, exist_ok=True)
        local_model = resolve_local_model(model_name, self.config.model_dir)
        explicit_model = os.path.abspath(os.path.expanduser(model_name))
        if local_model is None and os.path.isdir(explicit_model):
            local_model = explicit_model
        if local_model is None and not self.config.allow_model_download:
            raise RuntimeError(
                f"model {model_name!r} is not installed; use the verified language/model "
                "installer before selecting it"
            )
        model_source = local_model or model_name
        cuda_dll_paths = configure_cuda_dll_paths()
        import ctranslate2
        from faster_whisper import WhisperModel

        requested = self.config.device.lower()
        candidates: list[tuple[str, str]] = []
        cuda_count = ctranslate2.get_cuda_device_count()
        if requested in ("auto", "cuda") and cuda_count > 0:
            compute = "float16" if self.config.compute_type == "auto" else self.config.compute_type
            candidates.append(("cuda", compute))
        if requested in ("auto", "cpu") or not candidates:
            compute = "int8" if self.config.compute_type == "auto" else self.config.compute_type
            candidates.append(("cpu", compute))

        last_error: Exception | None = None
        for device, compute_type in candidates:
            self.emitter.send(
                "status",
                state="initializing_gpu" if device == "cuda" else "loading_model",
                model=model_name,
                backend=device,
                compute_type=compute_type,
            )
            try:
                self._model = WhisperModel(
                    model_source,
                    device=device,
                    compute_type=compute_type,
                    download_root=self.config.model_dir,
                    local_files_only=not self.config.allow_model_download,
                )
                # Some CUDA DLL failures surface only on the first encoder call,
                # so keep a tiny smoke inference inside the CPU-fallback boundary.
                smoke_segments, _ = self._model.transcribe(
                    np.zeros((SAMPLE_RATE,), dtype=np.float32),
                    language="en",
                    task="transcribe",
                    beam_size=1,
                    condition_on_previous_text=False,
                )
                list(smoke_segments)
                translation_smoke, _ = self._model.transcribe(
                    np.zeros((SAMPLE_RATE,), dtype=np.float32),
                    language="ru",
                    task="translate",
                    beam_size=1,
                    condition_on_previous_text=False,
                    max_new_tokens=32,
                )
                list(translation_smoke)
                self._backend = f"{device}/{compute_type}"
                self.emitter.send(
                    "status",
                    state="listening",
                    model=model_name,
                    backend=device,
                    compute_type=compute_type,
                    cuda_devices=cuda_count,
                    cuda_dll_paths=cuda_dll_paths,
                    local_processing=True,
                )
                return
            except Exception as error:
                last_error = error
                self.emitter.send(
                    "warning",
                    code="model_backend_failed",
                    backend=device,
                    message=str(error),
                )
                if device == "cuda" and not any(item[0] == "cpu" for item in candidates):
                    candidates.append(("cpu", "int8"))
        raise RuntimeError(f"could not load Whisper model {model_name}: {last_error}")

    @staticmethod
    def _looks_repetitive(text: str) -> bool:
        words = re.findall(r"\w+", text.casefold())
        compact = "".join(character for character in text.casefold() if not character.isspace())
        # Multilingual decoder loops can repeat a grapheme/virama sequence
        # inside one enormous token, so word n-grams alone are insufficient.
        for width in range(1, min(9, len(compact) // 6 + 1)):
            pattern = re.compile(rf"(.{{{width}}})\1{{5,}}", flags=re.UNICODE)
            match = pattern.search(compact)
            if match and len(match.group(0)) >= max(12, len(compact) // 3):
                return True
        if len(words) < 8:
            return False
        trigrams = [tuple(words[index : index + 3]) for index in range(len(words) - 2)]
        if len(set(trigrams)) <= max(1, len(trigrams) // 3):
            return True
        # Catch longer decoder loops that contain enough unique lead-in text
        # to evade a global trigram ratio check.
        for width in range(3, min(9, len(words) // 3 + 1)):
            counts: dict[tuple[str, ...], int] = {}
            for index in range(len(words) - width + 1):
                phrase = tuple(words[index : index + width])
                counts[phrase] = counts.get(phrase, 0) + 1
            if any(count >= 3 and count * width >= len(words) // 2 for count in counts.values()):
                return True
        return False

    @staticmethod
    def _collapse_sentence_loops(text: str) -> str:
        """Keep emphasis, but cap identical adjacent decoded sentences at two."""
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        result: list[str] = []
        previous = ""
        repeats = 0
        for sentence in sentences:
            comparable = " ".join(re.findall(r"\w+", sentence.casefold()))
            if comparable and comparable == previous:
                repeats += 1
                if repeats >= 2:
                    continue
            else:
                previous = comparable
                repeats = 0
            result.append(sentence)
        return " ".join(result)

    @staticmethod
    def _task_for_language(language: str | None) -> str:
        # English needs faithful transcription. Every other detected language,
        # including Russian, uses Whisper's speech-to-English translation task.
        return "transcribe" if language == "en" else "translate"

    def _reset_language_session(self, reason: str) -> None:
        previous = self._language_lock.reset()
        self._context = ""
        self._source_context.clear()
        self._recent_final_audio = np.empty((0,), dtype=np.float32)
        self._recent_outputs.clear()
        self._session_glossary.reset()
        self._translation_memory.reset()
        self.emitter.send(
            "language",
            state="reset",
            reason=reason,
            previous_language=previous,
        )

    def _maybe_reset_language_after_silence(self, job: InferenceJob) -> None:
        if self.config.source_language or job.segment_id == self._last_seen_segment_id:
            return
        self._last_seen_segment_id = job.segment_id
        if self._last_final_capture_end_unix_ms is None:
            return
        audio_duration_ms = job.audio.size * 1000 // SAMPLE_RATE
        speech_window_start_ms = job.audio_capture_end_unix_ms - audio_duration_ms
        silence_ms = speech_window_start_ms - self._last_final_capture_end_unix_ms
        reset_ms = round(self.config.language_reset_silence_seconds * 1000)
        if silence_ms >= reset_ms:
            self._reset_language_session("long_silence")

    def _detect_language(self, job: InferenceJob) -> tuple[str | None, float, bool]:
        if self.config.source_language:
            return self.config.source_language, 1.0, True
        self._maybe_reset_language_after_silence(job)
        if not job.is_final and (current := self._language_lock.current()) is not None:
            return current.language, current.confidence, True

        # A substantive current utterance is sufficient evidence by itself and
        # avoids an old source dominating a language change. Very short speech
        # borrows bounded prior audio for more reliable identification.
        current_audio = job.audio[-(8 * SAMPLE_RATE) :]
        if current_audio.size >= 3 * SAMPLE_RATE:
            context_audio = current_audio
        else:
            context_audio = np.concatenate((self._recent_final_audio, current_audio))
            context_audio = context_audio[-(8 * SAMPLE_RATE) :]
        language, probability, _ = self._model.detect_language(
            audio=context_audio,
            vad_filter=False,
            language_detection_segments=1,
            language_detection_threshold=0.70,
        )
        if job.is_final:
            decision = self._language_lock.observe(
                language,
                probability,
                evidence_audio_ms=round(context_audio.size * 1000 / SAMPLE_RATE),
            )
            if decision.changed_from is not None:
                self._recent_final_audio = np.empty((0,), dtype=np.float32)
                self._context = ""
                self._source_context.clear()
                self._session_glossary.reset()
                self._translation_memory.reset()
                self.emitter.send(
                    "language",
                    state="changed",
                    previous_language=decision.changed_from,
                    source_language=decision.language,
                    language_confidence=float(probability),
                )
            return decision.language, decision.confidence, decision.locked

        current = self._language_lock.current()
        if current is not None:
            return current.language, current.confidence, True
        return language, probability, False

    def _transcribe_source_final(
        self, job: InferenceJob, language: str
    ) -> tuple[str, int, float | None, float | None, bool]:
        """Accurate source-language final pass, independent from translation."""
        source_started = monotonic_ms()
        source_segments, _ = self._model.transcribe(
            job.audio,
            task="transcribe",
            language=language,
            beam_size=3,
            best_of=1,
            temperature=0.0,
            condition_on_previous_text=False,
            initial_prompt=(self._source_context.get(language, "")[-240:] or None),
            vad_filter=False,
            no_speech_threshold=0.60,
            log_prob_threshold=-1.0,
            compression_ratio_threshold=2.4,
            without_timestamps=False,
            # The VAD window is at most eight seconds. A 128-token ceiling is
            # deliberately generous for dense multilingual speech while still
            # preventing a malformed source decode from blocking finalization.
            max_new_tokens=SOURCE_TRANSCRIPTION_MAX_NEW_TOKENS,
        )
        materialized = list(source_segments)
        source_text = " ".join(item.text.strip() for item in materialized).strip()
        source_text = self._collapse_sentence_loops(source_text)
        source_avg_logprob = (
            sum(float(item.avg_logprob) for item in materialized) / len(materialized)
            if materialized
            else None
        )
        source_no_speech = (
            max(float(item.no_speech_prob) for item in materialized)
            if materialized
            else 1.0
        )
        source_duration_ms = monotonic_ms() - source_started
        source_suppressed = (
            not source_text
            or not re.search(r"\w", source_text, flags=re.UNICODE)
            or source_no_speech > 0.80
            or self._looks_repetitive(source_text)
        )
        if (
            source_text
            and not source_suppressed
        ):
            previous = self._source_context.get(language, "")
            self._source_context[language] = (previous + " " + source_text).strip()[-480:]
            confidence = (
                max(0.0, min(1.0, math.exp(source_avg_logprob)))
                if source_avg_logprob is not None
                else 0.0
            )
            for candidate in re.findall(r"(?<!\w)[A-Z][A-Za-z0-9-]{2,}(?!\w)", source_text):
                self._session_glossary.observe(candidate, confidence)
        return (
            "" if source_suppressed else source_text,
            source_duration_ms,
            source_avg_logprob,
            source_no_speech,
            source_suppressed,
        )

    @staticmethod
    def _quality_rank(report: Any) -> tuple[int, int, int]:
        critical = sum(issue.severity == "critical" for issue in report.issues)
        high = sum(issue.severity == "high" for issue in report.issues)
        return critical, high, len(report.issues)

    def _translate_verification_pass(
        self, job: InferenceJob, language: str
    ) -> tuple[str, int, float | None, float, float, bool]:
        """Run one bounded stronger decode after a semantic guard fails."""
        started = monotonic_ms()
        segments, _ = self._model.transcribe(
            job.audio,
            task="translate",
            language=language,
            beam_size=5,
            best_of=1,
            temperature=0.0,
            condition_on_previous_text=False,
            initial_prompt=None,
            vad_filter=False,
            no_speech_threshold=0.60,
            log_prob_threshold=-1.0,
            compression_ratio_threshold=2.4,
            without_timestamps=True,
            max_new_tokens=DIRECT_TRANSLATION_MAX_NEW_TOKENS,
        )
        materialized = list(segments)
        text = self._collapse_sentence_loops(
            " ".join(segment.text.strip() for segment in materialized).strip()
        )
        avg_logprob = (
            sum(float(segment.avg_logprob) for segment in materialized) / len(materialized)
            if materialized
            else None
        )
        no_speech_probability = (
            max(float(segment.no_speech_prob) for segment in materialized)
            if materialized
            else 1.0
        )
        compression_ratio = (
            max(float(segment.compression_ratio) for segment in materialized)
            if materialized
            else 0.0
        )
        suppressed = (
            not text
            or not re.search(r"\w", text, flags=re.UNICODE)
            or no_speech_probability > 0.80
            or compression_ratio > 2.60
            or self._looks_repetitive(text)
        )
        return (
            text,
            monotonic_ms() - started,
            avg_logprob,
            no_speech_probability,
            compression_ratio,
            suppressed,
        )

    def _decode(self, job: InferenceJob) -> None:
        started = monotonic_ms()
        language, language_probability, language_stable = self._detect_language(job)
        inference_task = self._task_for_language(language)
        self.emitter.send(
            "status",
            state="transcribing" if inference_task == "transcribe" else "translating",
            segment_id=job.segment_id,
            source_language=language,
            inference_task=inference_task,
        )
        segments, info = self._model.transcribe(
            job.audio,
            task=inference_task,
            language=language,
            beam_size=3 if job.is_final else 1,
            best_of=1,
            temperature=0.0,
            condition_on_previous_text=False,
            # English translation text is unsafe context for a non-English
            # decoder and can create cross-segment hallucination loops.
            initial_prompt=(self._context[-180:] or None) if language == "en" else None,
            vad_filter=False,
            no_speech_threshold=0.60,
            log_prob_threshold=-1.0,
            compression_ratio_threshold=2.4,
            without_timestamps=not job.is_final,
            max_new_tokens=(
                DIRECT_TRANSLATION_MAX_NEW_TOKENS
                if inference_task == "translate"
                else None
            ),
        )
        materialized = list(segments)
        text = " ".join(segment.text.strip() for segment in materialized).strip()
        text = self._collapse_sentence_loops(text)
        avg_logprob = (
            sum(segment.avg_logprob for segment in materialized) / len(materialized)
            if materialized
            else None
        )
        no_speech_probability = (
            max(segment.no_speech_prob for segment in materialized) if materialized else 1.0
        )
        compression_ratio = (
            max(segment.compression_ratio for segment in materialized)
            if materialized
            else 0.0
        )
        cross_segment_loop = (
            len(self._recent_outputs) >= 2
            and all(previous.casefold() == text.casefold() for previous in self._recent_outputs)
            and language_probability < 0.60
        )
        weak_no_speech = (
            no_speech_probability > 0.55
            and (avg_logprob is None or avg_logprob < -0.65)
        )
        weak_provisional_language = (
            not language_stable and language_probability < 0.55
        )
        suppressed = (
            not text
            or not re.search(r"\w", text, flags=re.UNICODE)
            or no_speech_probability > 0.80
            or weak_no_speech
            or weak_provisional_language
            or compression_ratio > 2.60
            or self._looks_repetitive(text)
            or cross_segment_loop
        )
        if job.is_final:
            self._recent_final_audio = np.concatenate(
                (self._recent_final_audio, job.audio)
            )[-(8 * SAMPLE_RATE) :]
        direct_pass_completed = monotonic_ms()
        source_text: str | None = None
        source_inference_duration_ms = 0
        source_avg_logprob: float | None = None
        source_no_speech_probability: float | None = None
        source_suppressed = False
        if job.is_final:
            if language == "en":
                source_text = text
                source_inference_duration_ms = direct_pass_completed - started
                source_avg_logprob = avg_logprob
                source_no_speech_probability = no_speech_probability
            elif language:
                (
                    source_text,
                    source_inference_duration_ms,
                    source_avg_logprob,
                    source_no_speech_probability,
                    source_suppressed,
                ) = self._transcribe_source_final(job, language)

        quality = None
        relevant_terms: tuple[str, ...] = ()
        translation_memory_hit = False
        verification_attempted = False
        verification_selected = False
        verification_inference_duration_ms = 0
        if job.is_final and source_text and language != "en":
            relevant_terms = tuple(
                dict.fromkeys(
                    self._terminology.relevant(source_text)
                    + tuple(
                        term
                        for term in self._session_glossary.locked_terms()
                        if term.casefold() in source_text.casefold()
                    )
                )
            )
            remembered = self._translation_memory.lookup(
                source_text,
                source_language=language or "unknown",
                context_key="|".join(relevant_terms),
            )
            if remembered is not None and not source_suppressed:
                text = remembered.translation
                suppressed = False
                translation_memory_hit = True

        if job.is_final and source_text and text and not suppressed and language != "en":
            quality = check_translation_quality(
                source_text,
                text,
                source_language=language or "unknown",
                required_terms=relevant_terms,
            )
            if quality.issues:
                verification_attempted = True
                (
                    verified_text,
                    verification_inference_duration_ms,
                    verified_avg_logprob,
                    verified_no_speech,
                    verified_compression_ratio,
                    verified_suppressed,
                ) = self._translate_verification_pass(job, language)
                if not verified_suppressed:
                    verified_quality = check_translation_quality(
                        source_text,
                        verified_text,
                        source_language=language or "unknown",
                        required_terms=relevant_terms,
                    )
                    if self._quality_rank(verified_quality) < self._quality_rank(quality):
                        text = verified_text
                        avg_logprob = verified_avg_logprob
                        no_speech_probability = verified_no_speech
                        compression_ratio = verified_compression_ratio
                        quality = verified_quality
                        verification_selected = True
            source_confidence = (
                max(0.0, min(1.0, math.exp(source_avg_logprob)))
                if source_avg_logprob is not None
                else 0.0
            )
            translation_confidence = (
                max(0.0, min(1.0, math.exp(avg_logprob)))
                if avg_logprob is not None
                else 0.0
            )
            if (
                (not translation_memory_hit or verification_selected)
                and quality.passed
                and not quality.issues
            ):
                self._translation_memory.remember(
                    source_text,
                    text,
                    source_language=language or "unknown",
                    context_key="|".join(relevant_terms),
                    confidence=min(source_confidence, translation_confidence),
                )
        if job.is_final and text and not suppressed:
            if language == "en":
                self._context = (self._context + " " + text).strip()[-360:]
            else:
                self._context = ""
            self._recent_outputs.append(text)
        completed = monotonic_ms()
        audio_duration_ms = job.audio.size * 1000 // SAMPLE_RATE
        inference_duration_ms = completed - started
        translation_inference_duration_ms = (
            direct_pass_completed - started + verification_inference_duration_ms
            if language != "en"
            else 0
        )
        if job.is_final:
            self._last_final_capture_end_unix_ms = job.audio_capture_end_unix_ms
        self.emitter.send(
            "transcript",
            segment_id=job.segment_id,
            revision=job.revision,
            text="" if suppressed else text,
            source_text=source_text,
            source_language=language or getattr(info, "language", "unknown"),
            language_confidence=float(language_probability),
            language_stable=language_stable,
            is_partial=not job.is_final,
            is_final=job.is_final,
            audio_start_ms=job.audio_start_ms,
            audio_end_ms=job.audio_end_ms,
            audio_capture_end_unix_ms=job.audio_capture_end_unix_ms,
            asr_started_ms=started,
            asr_completed_ms=completed,
            backend=self._backend,
            inference_task=inference_task,
            asr_engine=f"faster-whisper/{self.config.selected_model}",
            translation_engine=(
                "identity"
                if language == "en"
                else (
                    "whisper-direct+verified-beam5"
                    if verification_selected
                    else "whisper-direct"
                )
            ),
            audio_duration_ms=audio_duration_ms,
            inference_duration_ms=inference_duration_ms,
            source_inference_duration_ms=source_inference_duration_ms,
            translation_inference_duration_ms=translation_inference_duration_ms,
            verification_inference_duration_ms=verification_inference_duration_ms,
            verification_attempted=verification_attempted,
            verification_selected=verification_selected,
            real_time_factor=(inference_duration_ms / max(audio_duration_ms, 1)),
            avg_logprob=avg_logprob,
            source_avg_logprob=source_avg_logprob,
            no_speech_probability=no_speech_probability,
            source_no_speech_probability=source_no_speech_probability,
            source_suppressed=source_suppressed,
            compression_ratio=float(compression_ratio),
            quality_passed=(quality.passed if quality is not None else None),
            quality_issues=(quality.to_dict()["issues"] if quality is not None else []),
            glossary_terms=list(relevant_terms),
            translation_memory_hit=translation_memory_hit,
            suppressed=suppressed,
        )

    def run(self) -> None:
        try:
            self._load_model()
            while True:
                job = self.jobs.get()
                if job is None:
                    return
                try:
                    self._decode(job)
                except Exception as error:
                    self.emitter.send(
                        "error",
                        code="asr_failed",
                        recoverable=True,
                        segment_id=job.segment_id,
                        message=str(error),
                    )
        except Exception as error:
            traceback.print_exc(file=sys.stderr)
            self.emitter.send(
                "error", code="model_load_failed", recoverable=False, message=str(error)
            )


class VadLoop:
    def __init__(
        self,
        config: WorkerConfig,
        audio_queue: queue.Queue[AudioChunk | None],
        jobs: LatestJobQueue,
        emitter: Emitter,
    ) -> None:
        self.config = config
        self.audio_queue = audio_queue
        self.jobs = jobs
        self.emitter = emitter
        self.vad = StreamingSileroVad()
        frame_ms = VAD_FRAME_SAMPLES * 1000 / SAMPLE_RATE
        self.pre_roll_frames = max(1, round(config.pre_roll_ms / frame_ms))
        self.end_frames = max(1, round(config.vad_end_ms / frame_ms))
        self.partial_frames = max(1, round(config.partial_interval_ms / frame_ms))
        self.max_frames = max(1, round(config.max_utterance_seconds * 1000 / frame_ms))
        self.pre_roll: deque[np.ndarray] = deque(maxlen=self.pre_roll_frames)
        self.utterance: list[np.ndarray] = []
        self.stream_samples = 0
        self.segment_id = 0
        self.revision = 0
        self.speech = False
        self.start_run = 0
        self.silence_run = 0
        self.last_partial_frame_count = 0
        self.capture_end_unix_ms = 0

    def _submit(self, is_final: bool) -> None:
        if not self.utterance:
            return
        audio = np.concatenate(self.utterance).astype(np.float32, copy=False)
        self.revision += 1
        end_ms = self.stream_samples * 1000 // SAMPLE_RATE
        start_ms = max(0, end_ms - audio.size * 1000 // SAMPLE_RATE)
        accepted_without_drop = self.jobs.put(
            InferenceJob(
                segment_id=self.segment_id,
                revision=self.revision,
                audio=audio,
                audio_start_ms=start_ms,
                audio_end_ms=end_ms,
                audio_capture_end_unix_ms=self.capture_end_unix_ms,
                is_final=is_final,
            )
        )
        if not accepted_without_drop:
            self.emitter.send("metric", name="asr_jobs_dropped", delta=1)

    def _end_speech(self, reason: str) -> None:
        self._submit(is_final=True)
        self.emitter.send(
            "vad",
            state="speech_ended",
            segment_id=self.segment_id,
            reason=reason,
            stream_ms=self.stream_samples * 1000 // SAMPLE_RATE,
        )
        self.speech = False
        self.start_run = 0
        self.silence_run = 0
        self.utterance = []
        self.pre_roll.clear()
        self.last_partial_frame_count = 0

    def _process_frame(self, frame: np.ndarray, probability: float) -> None:
        self.stream_samples += frame.size
        if not self.speech:
            self.pre_roll.append(frame)
            self.start_run = self.start_run + 1 if probability >= self.config.vad_threshold else 0
            if self.start_run >= 2:
                self.speech = True
                self.segment_id += 1
                self.revision = 0
                self.utterance = list(self.pre_roll)
                self.last_partial_frame_count = len(self.utterance)
                self.emitter.send(
                    "vad",
                    state="speech_started",
                    segment_id=self.segment_id,
                    probability=probability,
                    stream_ms=self.stream_samples * 1000 // SAMPLE_RATE,
                )
            return

        self.utterance.append(frame)
        self.silence_run = self.silence_run + 1 if probability < 0.35 else 0
        utterance_frames = len(self.utterance)
        if utterance_frames - self.last_partial_frame_count >= self.partial_frames:
            self._submit(is_final=False)
            self.last_partial_frame_count = utterance_frames
        if self.silence_run >= self.end_frames:
            self._end_speech("silence")
        elif utterance_frames >= self.max_frames:
            self._end_speech("maximum_duration")

    def run(self) -> None:
        try:
            while True:
                chunk = self.audio_queue.get()
                if chunk is None:
                    if self.speech:
                        self._end_speech("shutdown")
                    return
                self.capture_end_unix_ms = chunk.capture_end_unix_ms
                for frame, probability in self.vad.feed(chunk.audio):
                    self._process_frame(frame, probability)
        except Exception as error:
            traceback.print_exc(file=sys.stderr)
            self.emitter.send("error", code="vad_failed", recoverable=False, message=str(error))


def decode_audio(message: dict[str, Any]) -> AudioChunk:
    if message.get("sample_rate") != SAMPLE_RATE:
        raise ValueError(f"worker requires {SAMPLE_RATE} Hz mono PCM")
    raw = base64.b64decode(message["pcm_s16le"], validate=True)
    if len(raw) % 2:
        raise ValueError("PCM byte count must be even")
    audio = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    return AudioChunk(audio=audio, capture_end_unix_ms=int(message["capture_end_unix_ms"]))


def serve() -> int:
    emitter = Emitter()
    emitter.send(
        "hello", worker="livesub-python", python=sys.version.split()[0], local_processing=True
    )
    audio_queue: queue.Queue[AudioChunk | None] | None = None
    jobs: LatestJobQueue | None = None
    threads: list[threading.Thread] = []
    dropped_audio = 0

    for line in sys.stdin:
        try:
            message = json.loads(line)
            message_type = message.get("type")
            if message.get("protocol", PROTOCOL_VERSION) != PROTOCOL_VERSION:
                raise ValueError("unsupported protocol version")
            if message_type == "configure":
                if threads:
                    raise ValueError("worker is already configured")
                config = WorkerConfig.from_message(message)
                audio_queue = queue.Queue(maxsize=32)
                jobs = LatestJobQueue(capacity=2)
                vad_loop = VadLoop(config, audio_queue, jobs, emitter)
                asr_loop = AsrLoop(config, jobs, emitter)
                threads = [
                    threading.Thread(target=vad_loop.run, name="vad", daemon=True),
                    threading.Thread(target=asr_loop.run, name="asr", daemon=True),
                ]
                for thread in threads:
                    thread.start()
                emitter.send("status", state="starting", preset=config.preset)
            elif message_type == "audio":
                if audio_queue is None:
                    raise ValueError("configure must be sent before audio")
                audio = decode_audio(message)
                try:
                    audio_queue.put_nowait(audio)
                except queue.Full:
                    dropped_audio += 1
                    emitter.send("metric", name="audio_chunks_dropped", value=dropped_audio)
            elif message_type == "ping":
                emitter.send("pong", request_id=message.get("request_id"))
            elif message_type == "shutdown":
                break
            else:
                raise ValueError(f"unknown message type: {message_type}")
        except Exception as error:
            emitter.send("error", code="protocol_error", recoverable=True, message=str(error))

    if audio_queue is not None:
        audio_queue.put(None)
    if threads:
        # VAD owns final utterance submission; flush it before closing ASR jobs.
        threads[0].join(timeout=10)
    if jobs is not None:
        jobs.close()
    if len(threads) > 1:
        threads[1].join(timeout=30)
    emitter.send("status", state="stopped")
    return 0


def protocol_self_test() -> int:
    audio = np.array([-32768, 0, 32767], dtype="<i2")
    message = {
        "sample_rate": SAMPLE_RATE,
        "capture_end_unix_ms": 1,
        "pcm_s16le": base64.b64encode(audio.tobytes()).decode("ascii"),
    }
    decoded = decode_audio(message)
    assert decoded.audio.shape == (3,)
    assert decoded.audio[0] == -1.0 and decoded.audio[-1] > 0.999
    jobs = LatestJobQueue(2)
    assert jobs.put(InferenceJob(1, 1, decoded.audio, 0, 1, 1, False))
    assert not jobs.put(InferenceJob(1, 2, decoded.audio, 0, 2, 2, False))
    assert jobs.get().revision == 2
    loop = "Hello. She is Shiv. She is Shiv. She is Shiv. She is Shiv."
    assert AsrLoop._collapse_sentence_loops(loop) == "Hello. She is Shiv. She is Shiv."
    assert AsrLoop._looks_repetitive("one two three one two three one two three")
    assert not re.search(r"\w", "... ...", flags=re.UNICODE)
    assert AsrLoop._task_for_language("en") == "transcribe"
    assert AsrLoop._task_for_language("ru") == "translate"
    assert AsrLoop._task_for_language("ja") == "translate"
    assert AsrLoop._task_for_language("hi") == "translate"
    assert resolve_local_model("missing", "missing") is None
    assert WorkerConfig().allow_model_download is False

    class CapturingEmitter:
        def __init__(self) -> None:
            self.events: list[tuple[str, dict[str, Any]]] = []

        def send(self, event_type: str, **fields: Any) -> None:
            self.events.append((event_type, fields))

    emitter = CapturingEmitter()
    asr = AsrLoop(WorkerConfig(), LatestJobQueue(), emitter)  # type: ignore[arg-type]
    asr._language_lock.observe("ru", 0.95, evidence_audio_ms=4_000)
    asr._last_seen_segment_id = 1
    asr._last_final_capture_end_unix_ms = 1_000
    after_long_silence = InferenceJob(
        2,
        1,
        np.zeros((SAMPLE_RATE,), dtype=np.float32),
        0,
        1_000,
        15_000,
        False,
    )
    asr._maybe_reset_language_after_silence(after_long_silence)
    assert asr._language_lock.locked_language is None
    assert emitter.events[-1][1]["reason"] == "long_silence"
    print("protocol self-test passed")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    options = parser.parse_args()
    raise SystemExit(protocol_self_test() if options.self_test else serve())
