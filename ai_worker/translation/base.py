"""Vendor-neutral text translation contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class TranslationCapabilities:
    engine_id: str
    model_id: str
    source_languages: tuple[str, ...]
    target_languages: tuple[str, ...]
    confidence: bool
    glossary_prompt: bool
    local_only: bool = True
    remote_code: bool = False
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class TranslationResult:
    source_text: str
    translated_text: str
    source_language: str
    target_language: str
    engine_id: str
    model_id: str
    inference_ms: int
    confidence: float | None = None
    alternatives: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["alternatives"] = list(self.alternatives)
        return value


class TranslationEngine(ABC):
    @abstractmethod
    def capabilities(self) -> TranslationCapabilities:
        raise NotImplementedError

    @abstractmethod
    def translate(
        self,
        text: str,
        *,
        source_language: str,
        target_language: str = "en",
        context: str = "",
        glossary: Sequence[str] = (),
    ) -> TranslationResult:
        raise NotImplementedError

    def warmup(self) -> None:
        """Optional local warmup."""

    def close(self) -> None:
        """Release provider resources when supported."""
