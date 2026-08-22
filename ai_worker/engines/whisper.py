"""faster-whisper implementations of the ASR engine contract."""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from .base import (
    ASREngine,
    ASRResult,
    EngineCapabilities,
    LanguageDetection,
    Timestamp,
)

SAMPLE_RATE = 16_000
DIRECT_TRANSLATION_MAX_NEW_TOKENS = 128
SOURCE_TRANSCRIPTION_MAX_NEW_TOKENS = 128


@dataclass(frozen=True)
class WhisperEngineConfig:
    engine_id: str
    model_id: str
    model_source: str
    model_dir: str
    device: str = "auto"
    compute_type: str = "auto"
    partial_beam_size: int = 1
    final_beam_size: int = 5
    local_files_only: bool = True


def _mono_16k(audio: Any, sample_rate: int) -> np.ndarray:
    value = np.asarray(audio, dtype=np.float32).reshape(-1)
    if sample_rate != SAMPLE_RATE:
        raise ValueError(
            f"ASR engine requires explicitly conditioned {SAMPLE_RATE} Hz audio; "
            f"received {sample_rate} Hz"
        )
    return np.ascontiguousarray(value)


class FasterWhisperASREngine(ASREngine):
    def __init__(self, config: WhisperEngineConfig) -> None:
        from faster_whisper import WhisperModel

        self.config = config
        device = config.device.lower()
        compute_type = config.compute_type.lower()
        if device == "auto":
            try:
                import ctranslate2

                device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
            except Exception:
                device = "cpu"
        if compute_type == "auto":
            compute_type = "float16" if device == "cuda" else "int8"
        self.device = device
        self.compute_type = compute_type
        self._model = WhisperModel(
            config.model_source,
            device=device,
            compute_type=compute_type,
            download_root=config.model_dir,
            local_files_only=config.local_files_only,
        )

    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            engine_id=self.config.engine_id,
            model_id=self.config.model_id,
            languages=("multilingual",),
            automatic_language_id=True,
            streaming=True,
            final_pass=True,
            timestamps=True,
            confidence=True,
            contextual_prompt=True,
            direct_english_translation=True,
            notes=(
                "Streaming is rolling-window re-decode, not an encoder-state streaming API.",
                f"Runtime backend is {self.device}/{self.compute_type}.",
            ),
        )

    def detect_language(
        self, audio: Any, sample_rate: int, *, context: str = ""
    ) -> LanguageDetection:
        del context
        pcm = _mono_16k(audio, sample_rate)
        language, probability, distribution = self._model.detect_language(
            audio=pcm,
            vad_filter=False,
            language_detection_segments=1,
            language_detection_threshold=0.0,
        )
        return LanguageDetection(
            language=language,
            confidence=float(probability),
            distribution={key: float(value) for key, value in distribution},
            evidence_audio_ms=round(pcm.size * 1000 / SAMPLE_RATE),
            source="whisper_encoder",
        )

    @staticmethod
    def _prompt(context: str, glossary: Sequence[str]) -> str | None:
        pieces = []
        if context.strip():
            pieces.append(context.strip()[-480:])
        clean_glossary = [item.strip() for item in glossary if item.strip()]
        if clean_glossary:
            pieces.append("Terminology: " + ", ".join(clean_glossary[:40]))
        return "\n".join(pieces) or None

    def _transcribe(
        self,
        audio: Any,
        sample_rate: int,
        *,
        language: str | None,
        context: str,
        glossary: Sequence[str],
        is_final: bool,
        task: str = "transcribe",
        beam_size_override: int | None = None,
    ) -> ASRResult:
        pcm = _mono_16k(audio, sample_rate)
        beam_size = beam_size_override or (
            self.config.final_beam_size
            if is_final
            else self.config.partial_beam_size
        )
        started = time.perf_counter_ns()
        segments, info = self._model.transcribe(
            pcm,
            task=task,
            language=language,
            beam_size=beam_size,
            best_of=1,
            temperature=0.0,
            condition_on_previous_text=False,
            # A prior English translation is not valid source-language context
            # for Whisper's translate decoder and can seed cross-window loops.
            initial_prompt=self._prompt(
                context if task == "transcribe" else "", glossary
            ),
            vad_filter=False,
            no_speech_threshold=0.60,
            log_prob_threshold=-1.0,
            compression_ratio_threshold=2.4,
            # The live worker owns utterance boundaries through VAD and does
            # not request Whisper's expensive per-word alignment. Keep this
            # adapter equivalent and return native segment timestamps below.
            word_timestamps=False,
            without_timestamps=not is_final,
            # Live VAD caps an utterance at eight seconds. This ceiling is far
            # above legitimate output for that window, while bounding decoder
            # loops that otherwise block the real-time queue for minutes.
            max_new_tokens=(
                DIRECT_TRANSLATION_MAX_NEW_TOKENS
                if task == "translate"
                else SOURCE_TRANSCRIPTION_MAX_NEW_TOKENS
            ),
        )
        materialized = list(segments)
        completed = time.perf_counter_ns()
        inference_ms = max(0, round((completed - started) / 1_000_000))
        audio_ms = round(pcm.size * 1000 / SAMPLE_RATE)
        text = " ".join(item.text.strip() for item in materialized).strip()
        avg_logprob = (
            sum(float(item.avg_logprob) for item in materialized) / len(materialized)
            if materialized
            else None
        )
        no_speech_probability = (
            max(float(item.no_speech_prob) for item in materialized)
            if materialized
            else 1.0
        )
        compression_ratio = (
            max(float(item.compression_ratio) for item in materialized)
            if materialized
            else 0.0
        )
        words: list[Timestamp] = []
        for segment in materialized:
            segment_words = getattr(segment, "words", None) or ()
            for word in segment_words:
                words.append(
                    Timestamp(
                        text=word.word.strip(),
                        start_ms=round(float(word.start) * 1000),
                        end_ms=round(float(word.end) * 1000),
                        confidence=(
                            float(word.probability)
                            if getattr(word, "probability", None) is not None
                            else None
                        ),
                    )
                )
            if not segment_words and segment.text.strip():
                words.append(
                    Timestamp(
                        text=segment.text.strip(),
                        start_ms=round(float(segment.start) * 1000),
                        end_ms=round(float(segment.end) * 1000),
                        confidence=max(
                            0.0,
                            min(1.0, math.exp(float(segment.avg_logprob))),
                        ),
                    )
                )
        confidence = (
            max(0.0, min(1.0, math.exp(avg_logprob)))
            if avg_logprob is not None
            else None
        )
        detected_language = language or getattr(info, "language", "unknown")
        language_probability = getattr(info, "language_probability", None)
        return ASRResult(
            text=text,
            language=str(detected_language),
            language_confidence=(
                float(language_probability)
                if language_probability is not None
                else None
            ),
            engine_id=self.config.engine_id,
            model_id=self.config.model_id,
            is_final=is_final,
            inference_ms=inference_ms,
            audio_ms=audio_ms,
            real_time_factor=inference_ms / max(audio_ms, 1),
            confidence=confidence,
            avg_logprob=avg_logprob,
            no_speech_probability=no_speech_probability,
            timestamps=tuple(words),
            metadata={
                "task": task,
                "backend": self.device,
                "compute_type": self.compute_type,
                "beam_size": beam_size,
                "compression_ratio": compression_ratio,
                "word_timestamps": False,
                "timestamp_granularity": "segment",
                "max_new_tokens": (
                    DIRECT_TRANSLATION_MAX_NEW_TOKENS
                    if task == "translate"
                    else SOURCE_TRANSCRIPTION_MAX_NEW_TOKENS
                ),
            },
        )

    def transcribe_stream(
        self,
        audio: Any,
        sample_rate: int,
        *,
        language: str | None = None,
        context: str = "",
        glossary: Sequence[str] = (),
    ) -> ASRResult:
        return self._transcribe(
            audio,
            sample_rate,
            language=language,
            context=context,
            glossary=glossary,
            is_final=False,
        )

    def transcribe_final(
        self,
        audio: Any,
        sample_rate: int,
        *,
        language: str | None = None,
        context: str = "",
        glossary: Sequence[str] = (),
    ) -> ASRResult:
        return self._transcribe(
            audio,
            sample_rate,
            language=language,
            context=context,
            glossary=glossary,
            is_final=True,
        )

    def translate_final(
        self,
        audio: Any,
        sample_rate: int,
        *,
        language: str | None,
        context: str = "",
        glossary: Sequence[str] = (),
    ) -> ASRResult:
        """Benchmark Whisper's direct speech-to-English route explicitly."""
        if language == "en":
            return self.transcribe_final(
                audio,
                sample_rate,
                language=language,
                context=context,
                glossary=glossary,
            )
        return self._transcribe(
            audio,
            sample_rate,
            language=language,
            context=context,
            glossary=glossary,
            is_final=True,
            task="translate",
        )

    def translate_final_with_beam(
        self,
        audio: Any,
        sample_rate: int,
        *,
        language: str,
        beam_size: int,
        glossary: Sequence[str] = (),
    ) -> ASRResult:
        if not 1 <= beam_size <= 10:
            raise ValueError("verification beam size must be between 1 and 10")
        return self._transcribe(
            audio,
            sample_rate,
            language=language,
            context="",
            glossary=glossary,
            is_final=True,
            task="translate",
            beam_size_override=beam_size,
        )

    def warmup(self) -> None:
        self.transcribe_stream(np.zeros((SAMPLE_RATE,), dtype=np.float32), SAMPLE_RATE, language="en")


class CurrentASREngine(FasterWhisperASREngine):
    """The exact current model family/configuration, retained as a baseline."""

    def __init__(
        self,
        model_source: str,
        model_dir: str,
        *,
        device: str = "auto",
        compute_type: str = "auto",
        local_files_only: bool = True,
    ) -> None:
        super().__init__(
            WhisperEngineConfig(
                engine_id="current-faster-whisper-small",
                model_id="Systran/faster-whisper-small@536b0662742c02347bc0e980a01041f333bce120",
                model_source=model_source,
                model_dir=model_dir,
                device=device,
                compute_type=compute_type,
                partial_beam_size=1,
                final_beam_size=3,
                local_files_only=local_files_only,
            )
        )


class WhisperLargeV3Engine(FasterWhisperASREngine):
    def __init__(
        self,
        model_source: str,
        model_dir: str,
        *,
        model_revision: str,
        device: str = "auto",
        compute_type: str = "auto",
        final_beam_size: int = 5,
        local_files_only: bool = True,
    ) -> None:
        if not model_revision.strip():
            raise ValueError("Whisper large-v3 requires an exact recorded revision")
        super().__init__(
            WhisperEngineConfig(
                engine_id="whisper-large-v3",
                model_id=f"Systran/faster-whisper-large-v3@{model_revision}",
                model_source=model_source,
                model_dir=model_dir,
                device=device,
                compute_type=compute_type,
                partial_beam_size=1,
                final_beam_size=final_beam_size,
                local_files_only=local_files_only,
            )
        )
