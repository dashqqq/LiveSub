"""Conservative terminology, session glossary, and translation memory."""

from __future__ import annotations

import re
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass
from typing import Sequence


DEFAULT_TERMS = (
    "Counter-Strike 2",
    "CS2",
    "Valorant",
    "Dota 2",
    "Discord",
    "Steam",
    "Tarkov",
    "Minecraft",
    "YouTube",
    "Twitch",
    "RTX",
    "FPS",
    "ping",
    "server",
    "rank",
    "match",
)


def _key(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _contains(text: str, term: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, flags=re.IGNORECASE) is not None


class TerminologyEngine:
    def __init__(self, terms: Sequence[str] = DEFAULT_TERMS) -> None:
        self._terms: OrderedDict[str, str] = OrderedDict()
        for term in terms:
            self.add(term)

    def add(self, canonical: str) -> None:
        value = canonical.strip()
        if value:
            self._terms[_key(value)] = value

    def relevant(self, text: str) -> tuple[str, ...]:
        return tuple(canonical for canonical in self._terms.values() if _contains(text, canonical))

    def missing(self, source_text: str, translated_text: str) -> tuple[str, ...]:
        return tuple(
            term
            for term in self.relevant(source_text)
            if not _contains(translated_text, term)
        )

    def all(self) -> tuple[str, ...]:
        return tuple(self._terms.values())


@dataclass
class _ObservedTerm:
    canonical: str
    hits: int = 0
    confidence_sum: float = 0.0
    locked: bool = False


class SessionGlossary:
    def __init__(
        self,
        *,
        minimum_hits: int = 2,
        minimum_average_confidence: float = 0.80,
        maximum_terms: int = 256,
    ) -> None:
        self.minimum_hits = max(2, minimum_hits)
        self.minimum_average_confidence = min(1.0, max(0.0, minimum_average_confidence))
        self.maximum_terms = max(16, maximum_terms)
        self._terms: OrderedDict[str, _ObservedTerm] = OrderedDict()

    def observe(self, canonical: str, confidence: float) -> bool:
        value = canonical.strip()
        if not value or not 0.0 <= confidence <= 1.0:
            return False
        key = _key(value)
        observed = self._terms.get(key)
        if observed is None:
            observed = _ObservedTerm(canonical=value)
            self._terms[key] = observed
        else:
            self._terms.move_to_end(key)
        observed.hits += 1
        observed.confidence_sum += confidence
        average = observed.confidence_sum / observed.hits
        if observed.hits >= self.minimum_hits and average >= self.minimum_average_confidence:
            observed.locked = True
        while len(self._terms) > self.maximum_terms:
            oldest_key, oldest = next(iter(self._terms.items()))
            if oldest.locked:
                # Locked terms are retained; evict the oldest unlocked term.
                removable = next((key for key, term in self._terms.items() if not term.locked), None)
                if removable is None:
                    break
                del self._terms[removable]
            else:
                del self._terms[oldest_key]
        return observed.locked

    def locked_terms(self) -> tuple[str, ...]:
        return tuple(item.canonical for item in self._terms.values() if item.locked)

    def reset(self) -> None:
        self._terms.clear()


@dataclass(frozen=True)
class MemoryEntry:
    source_text: str
    translation: str
    source_language: str
    context_key: str
    confidence: float


class TranslationMemory:
    def __init__(self, maximum_entries: int = 512, minimum_confidence: float = 0.75) -> None:
        self.maximum_entries = max(16, maximum_entries)
        self.minimum_confidence = min(1.0, max(0.0, minimum_confidence))
        self._entries: OrderedDict[tuple[str, str, str], MemoryEntry] = OrderedDict()

    @staticmethod
    def _entry_key(source_text: str, source_language: str, context_key: str) -> tuple[str, str, str]:
        return source_language, _key(source_text), _key(context_key)

    def remember(
        self,
        source_text: str,
        translation: str,
        *,
        source_language: str,
        context_key: str = "",
        confidence: float,
    ) -> bool:
        if confidence < self.minimum_confidence or not source_text.strip() or not translation.strip():
            return False
        key = self._entry_key(source_text, source_language, context_key)
        self._entries[key] = MemoryEntry(
            source_text=source_text,
            translation=translation,
            source_language=source_language,
            context_key=context_key,
            confidence=confidence,
        )
        self._entries.move_to_end(key)
        while len(self._entries) > self.maximum_entries:
            self._entries.popitem(last=False)
        return True

    def lookup(
        self,
        source_text: str,
        *,
        source_language: str,
        context_key: str = "",
    ) -> MemoryEntry | None:
        key = self._entry_key(source_text, source_language, context_key)
        value = self._entries.get(key)
        if value is not None:
            self._entries.move_to_end(key)
        return value

    def reset(self) -> None:
        self._entries.clear()
