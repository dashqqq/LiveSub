#!/usr/bin/env python3
"""Run a pinned local ASR candidate over registered corpus audio.

This command never promotes a model and never downloads weights by default. It
writes one append-safe JSONL prediction per case so interrupted benchmark runs
retain completed evidence.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import subprocess
import sys
import traceback
from collections import Counter, deque
from dataclasses import replace
from pathlib import Path
from typing import Any

BENCHMARK_PACKAGE_ROOT = os.environ.get("LIVESUB_BENCHMARK_PACKAGE_ROOT")
if BENCHMARK_PACKAGE_ROOT:
    package_root = Path(BENCHMARK_PACKAGE_ROOT).resolve()
    if not package_root.is_dir():
        raise RuntimeError(f"benchmark package root does not exist: {package_root}")
    sys.path.insert(0, str(package_root))

import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WORKSPACE = Path(__file__).resolve().parents[1]
BENCHMARK_ROOT = Path(__file__).resolve().parent
for import_root in (WORKSPACE, BENCHMARK_ROOT, WORKSPACE / "ai_worker"):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from ai_worker.engines import CurrentASREngine, Qwen3ASREngine, WhisperLargeV3Engine
from ai_worker.worker import (
    VAD_FRAME_SAMPLES,
    StreamingSileroVad,
    configure_cuda_dll_paths,
)
from ai_worker.translation.quality import check_translation_quality
from livesub_eval.corpus import CorpusCase, load_corpus
from livesub_eval.metrics import percentile, repetition_loop

SAMPLE_RATE = 16_000


def quality_rank(report: Any) -> tuple[int, int, int]:
    return (
        sum(issue.severity == "critical" for issue in report.issues),
        sum(issue.severity == "high" for issue in report.issues),
        len(report.issues),
    )


def vad_identity(model_path: Path | None) -> tuple[str, str]:
    if model_path is None:
        import faster_whisper

        resolved = Path(faster_whisper.__file__).resolve().parent / "assets" / "silero_vad_v6.onnx"
        label = f"faster-whisper-{getattr(faster_whisper, '__version__', 'unknown')}/silero_vad_v6.onnx"
    else:
        resolved = model_path.resolve()
        label = str(resolved)
    if not resolved.is_file():
        raise FileNotFoundError(f"VAD model does not exist: {resolved}")
    digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    return label, digest


def live_vad_segments(
    audio: np.ndarray,
    *,
    speech_threshold: float = 0.50,
    end_threshold: float = 0.35,
    minimum_silence_ms: int = 450,
    speech_padding_ms: int = 400,
    maximum_utterance_seconds: float = 8.0,
    model_path: Path | None = None,
) -> list[tuple[np.ndarray, int, int]]:
    """Reproduce the live worker's speech-boundary segmentation policy."""
    vad = StreamingSileroVad(model_path)
    frame_ms = VAD_FRAME_SAMPLES * 1000 / SAMPLE_RATE
    pre_roll = deque(maxlen=max(1, round(speech_padding_ms / frame_ms)))
    end_frames = max(1, round(minimum_silence_ms / frame_ms))
    max_frames = max(1, round(maximum_utterance_seconds * 1000 / frame_ms))
    utterance: list[np.ndarray] = []
    segments: list[tuple[np.ndarray, int, int]] = []
    stream_samples = 0
    start_run = 0
    silence_run = 0
    speech = False

    def finish() -> None:
        nonlocal utterance, start_run, silence_run, speech
        if utterance:
            segment = np.concatenate(utterance).astype(np.float32, copy=False)
            end_ms = stream_samples * 1000 // SAMPLE_RATE
            start_ms = max(0, end_ms - segment.size * 1000 // SAMPLE_RATE)
            segments.append((segment, start_ms, end_ms))
        utterance = []
        pre_roll.clear()
        start_run = 0
        silence_run = 0
        speech = False

    for frame, probability in vad.feed(audio):
        stream_samples += frame.size
        if not speech:
            pre_roll.append(frame)
            start_run = start_run + 1 if probability >= speech_threshold else 0
            if start_run >= 2:
                speech = True
                utterance = list(pre_roll)
            continue
        utterance.append(frame)
        silence_run = silence_run + 1 if probability < end_threshold else 0
        if silence_run >= end_frames or len(utterance) >= max_frames:
            finish()
    if speech:
        finish()
    return segments


def decode_audio(path: Path) -> np.ndarray:
    """Decode any PyAV-supported fixture to 16 kHz mono float32."""
    import av

    container = av.open(str(path))
    if not container.streams.audio:
        raise ValueError(f"no audio stream: {path}")
    resampler = av.AudioResampler(format="flt", layout="mono", rate=SAMPLE_RATE)
    chunks: list[np.ndarray] = []
    try:
        for frame in container.decode(audio=0):
            converted = resampler.resample(frame)
            if converted is None:
                continue
            frames = converted if isinstance(converted, list) else [converted]
            for item in frames:
                chunks.append(np.asarray(item.to_ndarray(), dtype=np.float32).reshape(-1))
        flushed = resampler.resample(None)
        if flushed is not None:
            frames = flushed if isinstance(flushed, list) else [flushed]
            for item in frames:
                chunks.append(np.asarray(item.to_ndarray(), dtype=np.float32).reshape(-1))
    finally:
        container.close()
    if not chunks:
        raise ValueError(f"decoded audio is empty: {path}")
    return np.ascontiguousarray(np.concatenate(chunks))


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def process_memory_mb() -> float | None:
    if os.name != "nt":
        return None
    counters = _ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    get_memory = psapi.GetProcessMemoryInfo
    get_memory.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_ProcessMemoryCounters),
        wintypes.DWORD,
    ]
    get_memory.restype = wintypes.BOOL
    handle = kernel32.GetCurrentProcess()
    if not get_memory(handle, ctypes.byref(counters), counters.cb):
        return None
    return counters.WorkingSetSize / (1024 * 1024)


def process_vram_mb() -> tuple[float | None, str | None]:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,used_memory",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None, None
    total = 0.0
    found = False
    for line in result.stdout.splitlines():
        pieces = [piece.strip() for piece in line.split(",")]
        if len(pieces) != 2:
            continue
        try:
            if int(pieces[0]) == os.getpid():
                total += float(pieces[1])
                found = True
        except ValueError:
            continue
    if found:
        return total, "process"
    # WDDM commonly reports per-process memory as N/A. Preserve an honest,
    # explicitly scoped device-level reading rather than fabricating a process
    # value or silently dropping the measurement.
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        values = [float(line.strip()) for line in result.stdout.splitlines() if line.strip()]
    except (OSError, ValueError, subprocess.SubprocessError):
        return None, None
    return (max(values), "device") if values else (None, None)


def local_whisper_snapshot(model_dir: Path, repository: str) -> tuple[str, str]:
    repository_path = model_dir / repository
    revision = (repository_path / "refs" / "main").read_text(encoding="utf-8").strip()
    snapshot = repository_path / "snapshots" / revision
    if not snapshot.is_dir():
        raise FileNotFoundError(f"missing local model snapshot: {snapshot}")
    return str(snapshot), revision


def create_engine(args: argparse.Namespace) -> Any:
    configure_cuda_dll_paths()
    if args.engine == "current":
        model_source, _ = local_whisper_snapshot(
            args.model_dir, "models--Systran--faster-whisper-small"
        )
        return CurrentASREngine(
            model_source,
            str(args.model_dir),
            device=args.device,
            compute_type=args.compute_type,
        )
    if args.engine == "whisper-large-v3":
        if args.model_path:
            model_source = str(args.model_path)
            revision = args.model_revision
        else:
            model_source, revision = local_whisper_snapshot(
                args.model_dir, "models--Systran--faster-whisper-large-v3"
            )
        return WhisperLargeV3Engine(
            model_source,
            str(args.model_dir),
            model_revision=revision,
            device=args.device,
            compute_type=args.compute_type,
            final_beam_size=args.final_beam_size,
        )
    size = "0.6B" if args.engine == "qwen3-0.6b" else "1.7B"
    if not args.model_path:
        raise ValueError("Qwen3-ASR requires --model-path to a staged verified directory")
    return Qwen3ASREngine(
        str(args.model_path),
        size=size,
        revision=args.model_revision,
        device=args.qwen_device,
        dtype=args.qwen_dtype,
        allow_download=args.allow_download,
    )


def selected_cases(args: argparse.Namespace) -> list[CorpusCase]:
    cases = load_corpus(args.corpus_root)
    if args.language:
        cases = [case for case in cases if case.language == args.language]
    if args.case:
        requested = set(args.case)
        cases = [case for case in cases if case.case_id in requested]
        missing = requested - {case.case_id for case in cases}
        if missing:
            raise ValueError(f"unknown case IDs: {', '.join(sorted(missing))}")
    return cases


def prediction_for(
    engine: Any,
    case: CorpusCase,
    route: str,
    *,
    force_language: bool,
    segmentation: str,
    vad_model_path: Path | None = None,
    vad_threshold: float = 0.50,
    vad_end_threshold: float = 0.35,
    vad_minimum_silence_ms: int = 450,
    vad_speech_padding_ms: int = 400,
) -> dict[str, Any]:
    audio = decode_audio(case.audio_path)
    vad_label, vad_sha256 = vad_identity(vad_model_path)
    language = case.language if force_language else None
    glossary = tuple(
        str(item)
        for key in ("names", "products", "critical_terms")
        for item in case.annotations.get(key, [])
    )
    memory_before = process_memory_mb()
    vram_before, vram_scope_before = process_vram_mb()
    segments = (
        [(audio, 0, round(audio.size * 1000 / SAMPLE_RATE))]
        if segmentation == "whole_file"
        else live_vad_segments(
            audio,
            speech_threshold=vad_threshold,
            end_threshold=vad_end_threshold,
            minimum_silence_ms=vad_minimum_silence_ms,
            speech_padding_ms=vad_speech_padding_ms,
            model_path=vad_model_path,
        )
    )
    if not segments:
        raise ValueError("live VAD found no speech segments")
    results = []
    source_results = []
    context = ""
    source_context = ""
    segment_metadata = []
    for segment_audio, start_ms, end_ms in segments:
        verification_metadata: dict[str, Any] = {}
        if route in ("direct_translation", "live"):
            translate = getattr(engine, "translate_final", None)
            if translate is None:
                raise ValueError(
                    f"{engine.capabilities().engine_id} has no direct translation route"
                )
            result = translate(
                segment_audio,
                SAMPLE_RATE,
                language=language,
                context=context,
                glossary=glossary,
            )
            if route == "live":
                direct_result = result
                resolved_language = language or direct_result.language
                source_result = engine.transcribe_final(
                    segment_audio,
                    SAMPLE_RATE,
                    language=resolved_language,
                    context=source_context,
                    glossary=glossary,
                )
                source_results.append(source_result)
                if source_result.text:
                    source_context = (
                        source_context + " " + source_result.text
                    ).strip()[-480:]
                initial_quality = check_translation_quality(
                    source_result.text,
                    direct_result.text,
                    source_language=resolved_language,
                    required_terms=glossary,
                )
                final_quality = initial_quality
                verification_result = None
                verification_selected = False
                if initial_quality.issues:
                    verify = getattr(engine, "translate_final_with_beam", None)
                    if verify is None:
                        raise ValueError(
                            f"{engine.capabilities().engine_id} has no bounded verification route"
                        )
                    verification_result = verify(
                        segment_audio,
                        SAMPLE_RATE,
                        language=resolved_language,
                        beam_size=5,
                        glossary=glossary,
                    )
                    verified_quality = check_translation_quality(
                        source_result.text,
                        verification_result.text,
                        source_language=resolved_language,
                        required_terms=glossary,
                    )
                    if quality_rank(verified_quality) < quality_rank(initial_quality):
                        result = verification_result
                        final_quality = verified_quality
                        verification_selected = True
                verification_ms = (
                    verification_result.inference_ms
                    if verification_result is not None
                    else 0
                )
                combined_inference_ms = (
                    direct_result.inference_ms
                    + source_result.inference_ms
                    + verification_ms
                )
                verification_metadata = {
                    "semantic_verification_attempted": verification_result is not None,
                    "semantic_verification_selected": verification_selected,
                    "direct_inference_ms": direct_result.inference_ms,
                    "source_inference_ms": source_result.inference_ms,
                    "verification_inference_ms": verification_ms,
                    "quality_initial": initial_quality.to_dict(),
                    "quality_final": final_quality.to_dict(),
                    "source_text": source_result.text,
                }
                result = replace(
                    result,
                    inference_ms=combined_inference_ms,
                    real_time_factor=combined_inference_ms / max(result.audio_ms, 1),
                    metadata={**dict(result.metadata), **verification_metadata},
                )
        else:
            result = engine.transcribe_final(
                segment_audio,
                SAMPLE_RATE,
                language=language,
                context=context,
                glossary=glossary,
            )
        results.append(result)
        if result.text and route != "live":
            context = (context + " " + result.text).strip()[-480:]
        segment_metadata.append(
            {
                "audio_start_ms": start_ms,
                "audio_end_ms": end_ms,
                "audio_ms": result.audio_ms,
                "inference_ms": result.inference_ms,
                "rtf": result.real_time_factor,
                "detected_language": result.language,
                "language_confidence": result.language_confidence,
                "confidence": result.confidence,
                "avg_logprob": result.avg_logprob,
                "no_speech_probability": result.no_speech_probability,
                "text": result.text,
                "compression_ratio": result.metadata.get("compression_ratio"),
                "decoder_loop": (
                    repetition_loop(result.text)
                    or float(result.metadata.get("compression_ratio") or 0) > 2.60
                ),
                **verification_metadata,
                "timestamps": [
                    {
                        "text": item.text,
                        "start_ms": start_ms + item.start_ms,
                        "end_ms": start_ms + item.end_ms,
                        "confidence": item.confidence,
                    }
                    for item in result.timestamps
                ],
            }
        )
    result = results[-1]
    combined_text = " ".join(item.text.strip() for item in results if item.text.strip())
    combined_source_text = " ".join(
        item.text.strip() for item in source_results if item.text.strip()
    )
    source_text = (
        combined_text
        if route == "source_asr"
        else combined_source_text
        if route == "live"
        else None
    )
    translation_text = (
        combined_text if route in ("direct_translation", "live") else None
    )
    language_votes = Counter(item.language for item in results if item.language)
    detected_language = language_votes.most_common(1)[0][0] if language_votes else None
    language_confidences = [
        item.language_confidence
        for item in results
        if item.language == detected_language and item.language_confidence is not None
    ]
    inference_values = [item.inference_ms for item in results]
    confidence_values = [item.confidence for item in results if item.confidence is not None]
    logprob_values = [item.avg_logprob for item in results if item.avg_logprob is not None]
    no_speech_values = [
        item.no_speech_probability
        for item in results
        if item.no_speech_probability is not None
    ]
    speech_audio_ms = sum(item.audio_ms for item in results)
    total_inference_ms = sum(inference_values)
    memory_after = process_memory_mb()
    vram_after, vram_scope_after = process_vram_mb()
    memory_samples = [value for value in (memory_before, memory_after) if value is not None]
    vram_samples = [value for value in (vram_before, vram_after) if value is not None]
    return {
        "schema_version": 1,
        "case_id": case.case_id,
        "engine_id": result.engine_id,
        "model_id": result.model_id,
        "route": route,
        "detected_language": detected_language,
        "language_confidence": (
            None
            if force_language
            else sum(language_confidences) / len(language_confidences)
            if language_confidences
            else None
        ),
        "source_text": source_text,
        "translation_text": translation_text,
        "display_text": None,
        "latency_ms": percentile(inference_values, 0.50),
        "rtf": total_inference_ms / max(speech_audio_ms, 1),
        "memory_mb": max(memory_samples) if memory_samples else None,
        "vram_mb": max(vram_samples) if vram_samples else None,
        "error": None,
        "metadata": {
            **dict(result.metadata),
            "benchmark_segmentation": segmentation,
            "vad_model": vad_label,
            "vad_model_sha256": vad_sha256,
            "vad_speech_threshold": vad_threshold,
            "vad_end_threshold": vad_end_threshold,
            "vad_minimum_silence_ms": vad_minimum_silence_ms,
            "vad_speech_padding_ms": vad_speech_padding_ms,
            "language_forced": force_language,
            "input_audio_ms": round(audio.size * 1000 / SAMPLE_RATE),
            "audio_ms": speech_audio_ms,
            "total_inference_ms": total_inference_ms,
            "segment_latencies_ms": inference_values,
            "segment_latency_p50_ms": percentile(inference_values, 0.50),
            "segment_latency_p95_ms": percentile(inference_values, 0.95),
            "segments": segment_metadata,
            "decoder_loop_segments": sum(
                bool(item["decoder_loop"]) for item in segment_metadata
            ),
            "decoder_loop_rate": (
                sum(bool(item["decoder_loop"]) for item in segment_metadata)
                / len(segment_metadata)
            ),
            "semantic_verification_attempts": sum(
                bool(item.get("semantic_verification_attempted"))
                for item in segment_metadata
            ),
            "semantic_verification_selections": sum(
                bool(item.get("semantic_verification_selected"))
                for item in segment_metadata
            ),
            "confidence": (
                sum(confidence_values) / len(confidence_values)
                if confidence_values
                else None
            ),
            "avg_logprob": (
                sum(logprob_values) / len(logprob_values) if logprob_values else None
            ),
            "no_speech_probability_max": max(no_speech_values) if no_speech_values else None,
            "vram_measurement_scope": vram_scope_after or vram_scope_before,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--engine",
        required=True,
        choices=("current", "whisper-large-v3", "qwen3-0.6b", "qwen3-1.7b"),
    )
    parser.add_argument(
        "--route", choices=("source_asr", "direct_translation", "live"), default="source_asr"
    )
    parser.add_argument(
        "--segmentation",
        choices=("live_vad", "whole_file"),
        default="live_vad",
        help="live_vad reproduces worker speech boundaries; whole_file is offline-only",
    )
    parser.add_argument("--corpus-root", type=Path, default=BENCHMARK_ROOT / "corpora")
    parser.add_argument("--language", choices=("ru", "ja", "hi", "en"))
    parser.add_argument("--case", action="append")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, default=WORKSPACE / "models")
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--model-revision", default="")
    parser.add_argument("--device", choices=("auto", "cuda", "cpu"), default="auto")
    parser.add_argument("--compute-type", default="auto")
    parser.add_argument("--final-beam-size", type=int, choices=range(1, 11), default=5)
    parser.add_argument("--qwen-device", default="cuda:0")
    parser.add_argument(
        "--qwen-dtype",
        choices=("float16", "bfloat16", "float32"),
        default="bfloat16",
    )
    parser.add_argument("--allow-download", action="store_true")
    parser.add_argument("--force-manifest-language", action="store_true")
    parser.add_argument("--vad-model-path", type=Path)
    parser.add_argument("--vad-threshold", type=float, default=0.50)
    parser.add_argument("--vad-end-threshold", type=float, default=0.35)
    parser.add_argument("--vad-minimum-silence-ms", type=int, default=450)
    parser.add_argument("--vad-speech-padding-ms", type=int, default=400)
    parser.add_argument("--skip-warmup", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    for name, value in (
        ("vad threshold", args.vad_threshold),
        ("VAD end threshold", args.vad_end_threshold),
    ):
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} must be between 0 and 1")
    if args.vad_minimum_silence_ms < 32 or args.vad_speech_padding_ms < 0:
        raise ValueError("VAD timing values are outside safe live bounds")

    cases = selected_cases(args)
    if not cases:
        raise ValueError("no corpus cases selected")
    engine = create_engine(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not args.skip_warmup:
        engine.warmup()
    try:
        with args.output.open("a", encoding="utf-8", buffering=1) as handle:
            for case in cases:
                try:
                    value = prediction_for(
                        engine,
                        case,
                        args.route,
                        force_language=args.force_manifest_language,
                        segmentation=args.segmentation,
                        vad_model_path=args.vad_model_path,
                        vad_threshold=args.vad_threshold,
                        vad_end_threshold=args.vad_end_threshold,
                        vad_minimum_silence_ms=args.vad_minimum_silence_ms,
                        vad_speech_padding_ms=args.vad_speech_padding_ms,
                    )
                except Exception as error:
                    value = {
                        "schema_version": 1,
                        "case_id": case.case_id,
                        "engine_id": engine.capabilities().engine_id,
                        "model_id": engine.capabilities().model_id,
                        "route": args.route,
                        "error": f"{type(error).__name__}: {error}",
                        "metadata": {"traceback": traceback.format_exc()},
                    }
                    if args.fail_fast:
                        raise
                handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
                if not args.quiet:
                    print(json.dumps(value, ensure_ascii=False, indent=2))
    finally:
        engine.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
