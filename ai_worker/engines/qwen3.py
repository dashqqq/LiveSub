"""Qwen3-ASR benchmark/final-pass adapter.

The official Transformers backend is usable for offline/final recognition. The
official streaming API currently requires its vLLM backend, so this adapter does
not pretend Transformers inference is native streaming. On Windows it is a
candidate accurate final pass until benchmarked within the live latency gate.
"""

from __future__ import annotations

import os
import time
from typing import Any, Sequence

import numpy as np

from .base import ASREngine, ASRResult, EngineCapabilities, LanguageDetection

SAMPLE_RATE = 16_000

LANGUAGE_NAMES = {
    "en": "English",
    "hi": "Hindi",
    "ja": "Japanese",
    "ru": "Russian",
}
LANGUAGE_CODES = {value.casefold(): key for key, value in LANGUAGE_NAMES.items()}


class Qwen3ASREngine(ASREngine):
    def __init__(
        self,
        model_path: str,
        *,
        size: str,
        revision: str,
        device: str = "cuda:0",
        dtype: str = "bfloat16",
        allow_download: bool = False,
    ) -> None:
        if size not in {"0.6B", "1.7B"}:
            raise ValueError("Qwen3-ASR size must be 0.6B or 1.7B")
        if not revision.strip():
            raise ValueError("Qwen3-ASR requires an exact recorded revision")
        if not allow_download and not os.path.isdir(model_path):
            raise FileNotFoundError(
                "Qwen3-ASR production/benchmark loading is local-only; stage and "
                f"verify the pinned model first: {model_path}"
            )
        import torch
        from qwen_asr import Qwen3ASRModel

        torch_dtype = {
            "float16": torch.float16,
            "bfloat16": torch.bfloat16,
            "float32": torch.float32,
        }.get(dtype)
        if torch_dtype is None:
            raise ValueError(f"unsupported Qwen dtype: {dtype}")
        self.size = size
        self.revision = revision
        self.model_path = model_path
        self.device = device
        self.dtype = dtype
        self._model = Qwen3ASRModel.from_pretrained(
            model_path,
            dtype=torch_dtype,
            device_map=device,
            max_inference_batch_size=1,
            max_new_tokens=256,
            local_files_only=not allow_download,
            trust_remote_code=False,
        )
        self._last_detection: LanguageDetection | None = None

    @property
    def engine_id(self) -> str:
        return f"qwen3-asr-{self.size.casefold()}"

    @property
    def model_id(self) -> str:
        return f"Qwen/Qwen3-ASR-{self.size}@{self.revision}"

    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            engine_id=self.engine_id,
            model_id=self.model_id,
            languages=("ru", "ja", "hi", "en", "48-more-languages-and-dialects"),
            automatic_language_id=True,
            streaming=False,
            final_pass=True,
            timestamps=False,
            confidence=False,
            contextual_prompt=False,
            direct_english_translation=False,
            notes=(
                "Official native streaming is vLLM-only and is not enabled by this Windows adapter.",
                "The decoder returns a language label but no calibrated LID probability.",
                "No trust_remote_code is used; the pinned qwen-asr package owns reviewed model code.",
                "Qwen system context is not used as Whisper-style prior transcript context.",
            ),
        )

    @staticmethod
    def _audio(audio: Any, sample_rate: int) -> np.ndarray:
        if sample_rate != SAMPLE_RATE:
            raise ValueError(f"Qwen3-ASR adapter requires {SAMPLE_RATE} Hz mono audio")
        return np.ascontiguousarray(np.asarray(audio, dtype=np.float32).reshape(-1))

    @staticmethod
    def _language_code(label: str) -> str:
        normalized = label.strip().casefold()
        return LANGUAGE_CODES.get(normalized, normalized or "unknown")

    def _transcribe(
        self,
        audio: Any,
        sample_rate: int,
        *,
        language: str | None,
        context: str,
        glossary: Sequence[str],
    ) -> ASRResult:
        pcm = self._audio(audio, sample_rate)
        # Qwen's `context` is inserted as a system message. Feeding a rolling
        # transcript here makes the decoder echo previous utterances; it is not
        # equivalent to Whisper's initial_prompt. Keep transcript context out
        # until a vendor-specific confirmation strategy is measured.
        del context
        prompt = ""
        clean_glossary = [item.strip() for item in glossary if item.strip()]
        if clean_glossary:
            prompt = (
                "Vocabulary hints; use only terms actually spoken in the audio: "
                + ", ".join(clean_glossary[:40])
            )
        force_language = LANGUAGE_NAMES.get(language or "") if language else None
        started = time.perf_counter_ns()
        results = self._model.transcribe(
            audio=(pcm, SAMPLE_RATE),
            language=force_language,
            context=prompt,
        )
        completed = time.perf_counter_ns()
        if len(results) != 1:
            raise RuntimeError(f"Qwen3-ASR returned {len(results)} results for one sample")
        result = results[0]
        inference_ms = max(0, round((completed - started) / 1_000_000))
        audio_ms = round(pcm.size * 1000 / SAMPLE_RATE)
        detected_language = self._language_code(str(result.language))
        self._last_detection = LanguageDetection(
            language=detected_language,
            confidence=None,
            distribution={},
            evidence_audio_ms=audio_ms,
            source="qwen_decoder_label",
        )
        return ASRResult(
            text=str(result.text).strip(),
            language=detected_language,
            language_confidence=None,
            engine_id=self.engine_id,
            model_id=self.model_id,
            is_final=True,
            inference_ms=inference_ms,
            audio_ms=audio_ms,
            real_time_factor=inference_ms / max(audio_ms, 1),
            confidence=None,
            timestamps=(),
            metadata={
                "backend": "transformers",
                "device": self.device,
                "dtype": self.dtype,
                "confidence_unavailable": True,
                "rolling_transcript_context_used": False,
            },
        )

    def detect_language(
        self, audio: Any, sample_rate: int, *, context: str = ""
    ) -> LanguageDetection:
        self._transcribe(
            audio,
            sample_rate,
            language=None,
            context=context,
            glossary=(),
        )
        assert self._last_detection is not None
        return self._last_detection

    def transcribe_stream(
        self,
        audio: Any,
        sample_rate: int,
        *,
        language: str | None = None,
        context: str = "",
        glossary: Sequence[str] = (),
    ) -> ASRResult:
        del audio, sample_rate, language, context, glossary
        raise NotImplementedError(
            "Qwen3-ASR Transformers streaming is not supported; use it only as a "
            "measured final pass or add the official vLLM backend on a supported platform"
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
        )

    def warmup(self) -> None:
        self.transcribe_final(
            np.zeros((SAMPLE_RATE,), dtype=np.float32),
            SAMPLE_RATE,
            language="en",
        )
