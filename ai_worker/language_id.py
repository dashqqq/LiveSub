"""Session-stable language identification from accumulated speech evidence."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LanguageDecision:
    language: str
    confidence: float
    locked: bool
    changed_from: str | None = None


class LanguageEvidenceAccumulator:
    """Lock language from useful speech and resist one-window source flips."""

    def __init__(
        self,
        *,
        score_decay: float = 0.72,
        immediate_lock_confidence: float = 0.85,
        immediate_lock_evidence_ms: int = 3_000,
        repeated_lock_hits: int = 2,
        repeated_lock_confidence: float = 0.60,
        contradiction_hits: int = 2,
        contradiction_confidence: float = 0.70,
    ) -> None:
        self.score_decay = min(1.0, max(0.0, score_decay))
        self.immediate_lock_confidence = min(
            1.0, max(0.0, immediate_lock_confidence)
        )
        self.immediate_lock_evidence_ms = max(250, immediate_lock_evidence_ms)
        self.repeated_lock_hits = max(2, repeated_lock_hits)
        self.repeated_lock_confidence = min(
            1.0, max(0.0, repeated_lock_confidence)
        )
        self.contradiction_hits = max(2, contradiction_hits)
        self.contradiction_confidence = min(
            1.0, max(0.0, contradiction_confidence)
        )
        self._scores: dict[str, float] = {}
        self._locked_language: str | None = None
        self._candidate_language: str | None = None
        self._candidate_hits = 0
        self._candidate_confidence = 0.0

    @property
    def locked_language(self) -> str | None:
        return self._locked_language

    def _locked_confidence(self) -> float:
        if self._locked_language is None:
            return 0.0
        total = max(sum(self._scores.values()), 0.001)
        return min(self._scores.get(self._locked_language, 0.0) / total, 1.0)

    def current(self) -> LanguageDecision | None:
        if self._locked_language is None:
            return None
        return LanguageDecision(
            language=self._locked_language,
            confidence=self._locked_confidence(),
            locked=True,
        )

    def observe(
        self,
        language: str,
        confidence: float,
        *,
        evidence_audio_ms: int,
    ) -> LanguageDecision:
        value = language.strip().casefold()
        if not value or value == "unknown":
            current = self.current()
            return current or LanguageDecision("unknown", 0.0, False)
        probability = min(1.0, max(0.0, float(confidence)))
        for key in tuple(self._scores):
            self._scores[key] *= self.score_decay
        self._scores[value] = self._scores.get(value, 0.0) + probability
        best = max(self._scores, key=self._scores.get)

        if value == self._candidate_language:
            self._candidate_hits += 1
            self._candidate_confidence += probability
        else:
            self._candidate_language = value
            self._candidate_hits = 1
            self._candidate_confidence = probability
        candidate_average = self._candidate_confidence / self._candidate_hits
        changed_from: str | None = None

        if self._locked_language is None:
            enough_immediate_evidence = (
                evidence_audio_ms >= self.immediate_lock_evidence_ms
                and best == value
                and probability >= self.immediate_lock_confidence
            )
            enough_repeated_evidence = (
                self._candidate_hits >= self.repeated_lock_hits
                and candidate_average >= self.repeated_lock_confidence
            )
            if enough_immediate_evidence or enough_repeated_evidence:
                self._locked_language = best
        elif value == self._locked_language:
            self._candidate_language = None
            self._candidate_hits = 0
            self._candidate_confidence = 0.0
        elif (
            self._candidate_hits >= self.contradiction_hits
            and candidate_average >= self.contradiction_confidence
        ):
            changed_from = self._locked_language
            self._locked_language = value
            self._scores = {value: probability}
            self._candidate_language = None
            self._candidate_hits = 0
            self._candidate_confidence = 0.0

        selected = self._locked_language or value
        selected_confidence = (
            self._locked_confidence()
            if self._locked_language is not None
            else probability
        )
        return LanguageDecision(
            language=selected,
            confidence=selected_confidence,
            locked=self._locked_language is not None,
            changed_from=changed_from,
        )

    def reset(self) -> str | None:
        previous = self._locked_language
        self._scores.clear()
        self._locked_language = None
        self._candidate_language = None
        self._candidate_hits = 0
        self._candidate_confidence = 0.0
        return previous
