"""Dependency-light accuracy and live-stability metrics.

WER/CER and critical-meaning checks are implemented locally so core evaluation
never disappears because an optional metric package is missing. SacreBLEU and
COMET are adapters with explicit availability reporting.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Sequence


_PUNCTUATION = re.compile(r"[^\w\s'%$€£¥₹.+:/-]", flags=re.UNICODE)
_SPACE = re.compile(r"\s+")
_NUMBER = re.compile(r"(?<!\w)[+-]?\d+(?:[.,:/-]\d+)*(?:st|nd|rd|th)?", re.IGNORECASE)
_PERCENT = re.compile(r"(?<!\w)[+-]?\d+(?:[.,]\d+)?\s*(?:%|percent\b)", re.IGNORECASE)
_TIME = re.compile(
    r"\b(?:[01]?\d|2[0-3]):[0-5]\d(?:\s*[ap]m)?\b|\b\d+(?:\.\d+)?\s*(?:seconds?|minutes?|hours?|days?)\b",
    re.IGNORECASE,
)
_CURRENCY = re.compile(
    r"(?:[$€£¥₹]\s*\d+(?:[.,]\d+)*)|(?:\b\d+(?:[.,]\d+)?\s*(?:usd|eur|gbp|jpy|inr|dollars?|euros?|pounds?|yen|rupees?|rubles?)\b)",
    re.IGNORECASE,
)
_NEGATIONS = {
    "not",
    "no",
    "never",
    "neither",
    "nor",
    "nothing",
    "nobody",
    "nowhere",
    "without",
    "don't",
    "doesn't",
    "didn't",
    "can't",
    "cannot",
    "won't",
    "wouldn't",
    "shouldn't",
    "isn't",
    "aren't",
    "wasn't",
    "weren't",
    "haven't",
    "hasn't",
    "hadn't",
}
_DIRECTIONS = {
    "left",
    "right",
    "north",
    "south",
    "east",
    "west",
    "upstairs",
    "downstairs",
    "above",
    "below",
    "behind",
    "ahead",
}


@dataclass(frozen=True)
class ErrorCounts:
    substitutions: int
    deletions: int
    insertions: int
    reference_units: int

    @property
    def errors(self) -> int:
        return self.substitutions + self.deletions + self.insertions

    @property
    def rate(self) -> float | None:
        if self.reference_units == 0:
            return None
        return self.errors / self.reference_units

    def to_dict(self) -> dict[str, int | float | None]:
        return {
            "substitutions": self.substitutions,
            "deletions": self.deletions,
            "insertions": self.insertions,
            "reference_units": self.reference_units,
            "errors": self.errors,
            "rate": self.rate,
        }


def normalize_text(text: str, *, strip_punctuation: bool = True) -> str:
    value = unicodedata.normalize("NFKC", text).replace("’", "'").casefold()
    if strip_punctuation:
        value = _PUNCTUATION.sub(" ", value)
    return _SPACE.sub(" ", value).strip()


def _edit_counts(reference: Sequence[str], hypothesis: Sequence[str]) -> ErrorCounts:
    # Each cell stores (total edits, substitutions, deletions, insertions).
    previous = [(index, 0, index, 0) for index in range(len(reference) + 1)]
    for hyp_index, hyp_item in enumerate(hypothesis, start=1):
        current = [(hyp_index, 0, 0, hyp_index)]
        for ref_index, ref_item in enumerate(reference, start=1):
            if ref_item == hyp_item:
                current.append(previous[ref_index - 1])
                continue
            substitution = previous[ref_index - 1]
            deletion = previous[ref_index]
            insertion = current[ref_index - 1]
            options = (
                (substitution[0] + 1, substitution[1] + 1, substitution[2], substitution[3]),
                (deletion[0] + 1, deletion[1], deletion[2] + 1, deletion[3]),
                (insertion[0] + 1, insertion[1], insertion[2], insertion[3] + 1),
            )
            current.append(min(options, key=lambda item: item))
        previous = current
    _, substitutions, deletions, insertions = previous[-1]
    return ErrorCounts(substitutions, deletions, insertions, len(reference))


def word_error_counts(reference: str, hypothesis: str) -> ErrorCounts:
    return _edit_counts(normalize_text(reference).split(), normalize_text(hypothesis).split())


def character_error_counts(reference: str, hypothesis: str) -> ErrorCounts:
    ref = list(normalize_text(reference).replace(" ", ""))
    hyp = list(normalize_text(hypothesis).replace(" ", ""))
    return _edit_counts(ref, hyp)


def add_error_counts(values: Iterable[ErrorCounts]) -> ErrorCounts:
    result = ErrorCounts(0, 0, 0, 0)
    for value in values:
        result = ErrorCounts(
            result.substitutions + value.substitutions,
            result.deletions + value.deletions,
            result.insertions + value.insertions,
            result.reference_units + value.reference_units,
        )
    return result


def percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    if not 0.0 <= quantile <= 1.0:
        raise ValueError("quantile must be in [0, 1]")
    ordered = sorted(float(value) for value in values)
    rank = quantile * (len(ordered) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    fraction = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _words(text: str) -> set[str]:
    return set(normalize_text(text, strip_punctuation=False).split())


def _present(text: str, term: str) -> bool:
    normalized_text = normalize_text(text, strip_punctuation=False)
    normalized_term = normalize_text(term, strip_punctuation=False)
    if not normalized_term:
        return True
    return re.search(rf"(?<!\w){re.escape(normalized_term)}(?!\w)", normalized_text) is not None


def _extract_set(pattern: re.Pattern[str], text: str) -> set[str]:
    return {normalize_text(match.group(0), strip_punctuation=False) for match in pattern.finditer(text)}


def critical_error_report(
    reference: str,
    hypothesis: str,
    annotations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    annotations = annotations or {}
    reference_words = _words(reference)
    hypothesis_words = _words(hypothesis)
    expected_negations = sorted(reference_words & _NEGATIONS)
    actual_negations = sorted(hypothesis_words & _NEGATIONS)
    expected_directions = sorted(reference_words & _DIRECTIONS)
    actual_directions = sorted(hypothesis_words & _DIRECTIONS)

    categories: dict[str, dict[str, Any]] = {}

    def record(category: str, expected: Iterable[str], actual: Iterable[str]) -> None:
        expected_values = sorted(set(expected))
        actual_values = sorted(set(actual))
        categories[category] = {
            "expected": expected_values,
            "actual": actual_values,
            "missing": sorted(set(expected_values) - set(actual_values)),
            "unexpected": sorted(set(actual_values) - set(expected_values)),
        }

    record("negation", expected_negations, actual_negations)
    record("numbers", _extract_set(_NUMBER, reference), _extract_set(_NUMBER, hypothesis))
    record("directions", expected_directions, actual_directions)
    record("time", _extract_set(_TIME, reference), _extract_set(_TIME, hypothesis))
    record("currency", _extract_set(_CURRENCY, reference), _extract_set(_CURRENCY, hypothesis))
    record("percentages", _extract_set(_PERCENT, reference), _extract_set(_PERCENT, hypothesis))

    for category in ("names", "products", "critical_terms"):
        terms = [str(value) for value in annotations.get(category, [])]
        categories[category] = {
            "expected": terms,
            "actual": [term for term in terms if _present(hypothesis, term)],
            "missing": [term for term in terms if not _present(hypothesis, term)],
            "unexpected": [],
        }

    # Extra negation is a polarity change; for other automatic categories only
    # missing or changed reference anchors count as critical by default.
    errors = sum(len(value["missing"]) for value in categories.values())
    errors += len(categories["negation"]["unexpected"])
    return {
        "errors": errors,
        "passed": errors == 0,
        "categories": categories,
    }


def sacrebleu_scores(references: Sequence[str], hypotheses: Sequence[str]) -> dict[str, Any]:
    if len(references) != len(hypotheses):
        raise ValueError("reference and hypothesis counts differ")
    if not references:
        return {"bleu": None, "chrf_pp": None, "available": False, "reason": "no reviewed pairs"}
    try:
        import sacrebleu
    except ImportError:
        return {
            "bleu": None,
            "chrf_pp": None,
            "available": False,
            "reason": "install benchmarks/requirements-metrics.txt",
        }
    return {
        "bleu": float(sacrebleu.corpus_bleu(list(hypotheses), [list(references)]).score),
        "chrf_pp": float(
            sacrebleu.corpus_chrf(list(hypotheses), [list(references)], word_order=2).score
        ),
        "available": True,
        "signature": "sacrebleu corpus_bleu + chrF++ word_order=2",
    }


def comet_scores(
    sources: Sequence[str], references: Sequence[str], hypotheses: Sequence[str]
) -> dict[str, Any]:
    if not (len(sources) == len(references) == len(hypotheses)):
        raise ValueError("COMET input counts differ")
    if not sources:
        return {"score": None, "available": False, "reason": "no reviewed triples"}
    # COMET is intentionally not downloaded implicitly. Model acquisition must
    # pass the same license/provenance process as a production model.
    return {
        "score": None,
        "available": False,
        "reason": "no reviewed, pinned COMET evaluator configured",
    }


def duplicate_rate(texts: Sequence[str]) -> float | None:
    normalized = [normalize_text(value) for value in texts if normalize_text(value)]
    if len(normalized) < 2:
        return None
    duplicates = sum(left == right for left, right in zip(normalized, normalized[1:]))
    return duplicates / (len(normalized) - 1)


def repetition_loop(text: str) -> bool:
    compact = "".join(character for character in normalize_text(text) if not character.isspace())
    for width in range(1, min(9, len(compact) // 6 + 1)):
        match = re.search(rf"(.{{{width}}})\1{{5,}}", compact, flags=re.UNICODE)
        if match and len(match.group(0)) >= max(12, len(compact) // 3):
            return True
    words = normalize_text(text).split()
    if len(words) < 6:
        return False
    for width in range(1, min(9, len(words) // 2 + 1)):
        phrases = Counter(tuple(words[index : index + width]) for index in range(len(words) - width + 1))
        if any(count >= 3 and count * width >= len(words) // 2 for count in phrases.values()):
            return True
    return False
