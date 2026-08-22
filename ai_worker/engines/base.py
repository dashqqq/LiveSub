"""Vendor-neutral contracts used by live and offline ASR orchestration.

The contract deliberately describes evidence an engine actually returns. A
missing confidence or timestamp is represented as ``None`` rather than a fake
value synthesized from an unrelated signal.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class EngineCapabilities:
    engine_id: str
    model_id: str
    languages: tuple[str, ...]
    automatic_language_id: bool
    streaming: bool
    final_pass: bool
    timestamps: bool
    confidence: bool
    contextual_prompt: bool
    direct_english_translation: bool
    local_only: bool = True
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["languages"] = list(self.languages)
        value["notes"] = list(self.notes)
        return value


@dataclass(frozen=True)
class LanguageDetection:
    language: str
    confidence: float | None
    distribution: Mapping[str, float] = field(default_factory=dict)
    evidence_audio_ms: int = 0
    source: str = "unknown"


@dataclass(frozen=True)
class Timestamp:
    text: str
    start_ms: int
    end_ms: int
    confidence: float | None = None


@dataclass(frozen=True)
class ASRResult:
    text: str
    language: str
    language_confidence: float | None
    engine_id: str
    model_id: str
    is_final: bool
    inference_ms: int
    audio_ms: int
    real_time_factor: float
    confidence: float | None = None
    avg_logprob: float | None = None
    no_speech_probability: float | None = None
    timestamps: tuple[Timestamp, ...] = ()
    alternatives: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["timestamps"] = [asdict(item) for item in self.timestamps]
        value["alternatives"] = list(self.alternatives)
        return value


class ASREngine(ABC):
    """ASR provider boundary.

    Audio is always mono float PCM. Callers must pass its actual sample rate;
    production adapters normalize to 16 kHz explicitly rather than assuming it.
    """

    @abstractmethod
    def capabilities(self) -> EngineCapabilities:
        raise NotImplementedError

    @abstractmethod
    def detect_language(
        self, audio: Any, sample_rate: int, *, context: str = ""
    ) -> LanguageDetection:
        raise NotImplementedError

    @abstractmethod
    def transcribe_stream(
        self,
        audio: Any,
        sample_rate: int,
        *,
        language: str | None = None,
        context: str = "",
        glossary: Sequence[str] = (),
    ) -> ASRResult:
        raise NotImplementedError

    @abstractmethod
    def transcribe_final(
        self,
        audio: Any,
        sample_rate: int,
        *,
        language: str | None = None,
        context: str = "",
        glossary: Sequence[str] = (),
    ) -> ASRResult:
        raise NotImplementedError

    def confidence(self, result: ASRResult) -> float | None:
        return result.confidence

    def timestamps(self, result: ASRResult) -> tuple[Timestamp, ...]:
        return result.timestamps

    def warmup(self) -> None:
        """Optional provider warmup. Implementations must use local audio only."""

    def close(self) -> None:
        """Release provider resources when supported."""
