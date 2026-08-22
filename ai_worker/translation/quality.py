"""Reference-free critical-meaning checks for the live translation path."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Sequence


@dataclass(frozen=True)
class QualityIssue:
    category: str
    severity: str
    source_evidence: str
    message: str


@dataclass(frozen=True)
class TranslationQualityReport:
    passed: bool
    issues: tuple[QualityIssue, ...]
    checked_categories: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "issues": [asdict(issue) for issue in self.issues],
            "checked_categories": list(self.checked_categories),
        }


_NUMBER = re.compile(r"(?<!\w)\d+(?:[.,:/-]\d+)*(?!\w)", re.UNICODE)
_NUMBER_WORDS = {
    "en": {
        "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
        "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
        "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
        "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
        "eighteen": "18", "nineteen": "19", "twenty": "20", "thirty": "30",
        "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70",
        "eighty": "80", "ninety": "90", "one hundred": "100",
        "one hundred fifty": "150", "one hundred and fifty": "150",
        "a hundred and fifty": "150",
    },
    "ru": {
        "ноль": "0", "один": "1", "одна": "1", "два": "2", "две": "2",
        "три": "3", "четыре": "4", "пять": "5", "шесть": "6", "семь": "7",
        "восемь": "8", "девять": "9", "десять": "10", "одиннадцать": "11",
        "двенадцать": "12", "тринадцать": "13", "четырнадцать": "14",
        "пятнадцать": "15", "шестнадцать": "16", "семнадцать": "17",
        "восемнадцать": "18", "девятнадцать": "19", "двадцать": "20",
        "тридцать": "30", "сорок": "40", "пятьдесят": "50", "шестьдесят": "60",
        "семьдесят": "70", "восемьдесят": "80", "девяносто": "90", "сто": "100",
        "сто пятьдесят": "150",
    },
    "ja": {
        "ゼロ": "0", "零": "0", "一": "1", "二": "2", "三": "3", "四": "4",
        "五": "5", "六": "6", "七": "7", "八": "8", "九": "9", "十": "10",
        "十一": "11", "十二": "12", "十三": "13", "十四": "14", "十五": "15",
        "二十": "20", "三十": "30", "四十": "40", "五十": "50", "百": "100",
        "百五十": "150",
    },
    "hi": {
        "शून्य": "0", "एक": "1", "दो": "2", "तीन": "3", "चार": "4",
        "पाँच": "5", "पांच": "5", "छह": "6", "सात": "7", "आठ": "8",
        "नौ": "9", "दस": "10", "ग्यारह": "11", "बारह": "12", "तेरह": "13",
        "चौदह": "14", "पंद्रह": "15", "पन्द्रह": "15", "बीस": "20",
        "तीस": "30", "चालीस": "40", "पचास": "50", "सौ": "100",
        "एक सौ पचास": "150", "डेढ़ सौ": "150",
        "pandrah": "15", "pachaas": "50", "sau": "100",
    },
}
_PERCENT_MARKERS = {
    "ru": ("%", "процент"),
    "ja": ("%", "パーセント"),
    "hi": ("%", "प्रतिशत", "फ़ीसदी", "फीसदी", "percent"),
}
_CURRENCY_MARKERS = {
    "ru": {"₽": "RUB", "руб": "RUB", "$": "USD", "доллар": "USD", "€": "EUR", "евро": "EUR"},
    "ja": {"¥": "JPY", "￥": "JPY", "円": "JPY", "$": "USD", "ドル": "USD", "€": "EUR", "ユーロ": "EUR"},
    "hi": {"₹": "INR", "रुप": "INR", "$": "USD", "डॉलर": "USD", "€": "EUR", "यूरो": "EUR"},
}
_EN_CURRENCY_MARKERS = {
    "RUB": ("₽", "rub", "ruble", "rouble"),
    "USD": ("$", "usd", "dollar"),
    "EUR": ("€", "eur", "euro"),
    "JPY": ("¥", "jpy", "yen"),
    "INR": ("₹", "inr", "rupee"),
}
_EN_NEGATION = re.compile(
    r"\b(?:no|not|never|neither|nor|nothing|nobody|without|cannot|can't|don't|doesn't|didn't|won't|wouldn't|shouldn't|isn't|aren't|wasn't|weren't|haven't|hasn't|hadn't)\b",
    re.IGNORECASE,
)
_SOURCE_NEGATION = {
    "ru": (" не ", "нет", "никогда", "нельзя"),
    "ja": ("ない", "ません", "じゃない", "ではない", "無い"),
    "hi": ("नहीं", "मत ", "कभी नहीं", "नही"),
}
_DIRECTIONS = {
    "ru": {
        "лев": "left",
        "прав": "right",
        "север": "north",
        "юг": "south",
        "наверху": "upstairs",
        "внизу": "downstairs",
    },
    "ja": {
        "左": "left",
        "右": "right",
        "北": "north",
        "南": "south",
        "上の階": "upstairs",
        "下の階": "downstairs",
    },
    "hi": {
        "बाएं": "left",
        "बायें": "left",
        "दाएं": "right",
        "दायें": "right",
        "उत्तर": "north",
        "दक्षिण": "south",
        "ऊपर": "upstairs",
        "नीचे": "downstairs",
    },
}
_SENTENCE_BOUNDARY = re.compile(r"[.!?。！？]+")
_SPACE_TOKEN_LANGUAGES = {"ru", "hi"}


def _repetition_loop(text: str) -> bool:
    words = re.findall(r"\w+", text.casefold(), flags=re.UNICODE)
    if len(words) >= 6:
        for width in range(1, min(9, len(words) // 2 + 1)):
            counts: dict[tuple[str, ...], int] = {}
            for index in range(len(words) - width + 1):
                phrase = tuple(words[index : index + width])
                counts[phrase] = counts.get(phrase, 0) + 1
            if any(count >= 3 and count * width >= len(words) // 2 for count in counts.values()):
                return True
    compact = "".join(character for character in text.casefold() if not character.isspace())
    for width in range(1, min(9, len(compact) // 6 + 1)):
        match = re.search(rf"(.{{{width}}})\1{{5,}}", compact, flags=re.UNICODE)
        if match and len(match.group(0)) >= max(12, len(compact) // 3):
            return True
    return False


def _ascii_digits(value: str) -> str:
    result = []
    for character in value:
        try:
            result.append(str(unicodedata.digit(character)))
        except (TypeError, ValueError):
            result.append(character)
    return "".join(result)


def _numbers(text: str, language: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", _ascii_digits(text)).casefold()
    values = {match.group(0) for match in _NUMBER.finditer(normalized)}
    words = _NUMBER_WORDS.get(language, {})
    if not words:
        return values
    phrases = sorted(words, key=len, reverse=True)
    if language == "ja":
        pattern = re.compile("|".join(re.escape(phrase) for phrase in phrases))
    else:
        pattern = re.compile(
            r"(?<!\w)(?:" + "|".join(re.escape(phrase) for phrase in phrases) + r")(?!\w)",
            re.UNICODE,
        )
    for match in pattern.finditer(normalized):
        values.add(words[match.group(0)])
    return values


def _source_currencies(text: str, language: str) -> set[str]:
    lowered = unicodedata.normalize("NFKC", text).casefold()
    return {
        currency
        for marker, currency in _CURRENCY_MARKERS.get(language, {}).items()
        if marker.casefold() in lowered
    }


def check_translation_quality(
    source_text: str,
    translated_text: str,
    *,
    source_language: str,
    required_terms: Sequence[str] = (),
) -> TranslationQualityReport:
    issues: list[QualityIssue] = []
    source_numbers = _numbers(source_text, source_language)
    translated_numbers = _numbers(translated_text, "en")
    for value in sorted(source_numbers - translated_numbers):
        issues.append(
            QualityIssue("number", "critical", value, f"number {value!r} is missing from English")
        )

    lowered_translation = translated_text.casefold()
    if any(marker in source_text.casefold() for marker in _PERCENT_MARKERS.get(source_language, ())):
        if "%" not in translated_text and "percent" not in lowered_translation:
            issues.append(
                QualityIssue(
                    "percentage",
                    "critical",
                    source_language,
                    "source percentage marker is missing from English",
                )
            )

    for currency in sorted(_source_currencies(source_text, source_language)):
        if not any(marker in lowered_translation for marker in _EN_CURRENCY_MARKERS[currency]):
            issues.append(
                QualityIssue(
                    "currency",
                    "critical",
                    currency,
                    f"source currency {currency} is missing from English",
                )
            )

    padded_source = f" {source_text.casefold()} "
    if any(term in padded_source for term in _SOURCE_NEGATION.get(source_language, ())):
        if _EN_NEGATION.search(translated_text) is None:
            issues.append(
                QualityIssue(
                    "negation",
                    "critical",
                    source_language,
                    "source appears negative but English has no recognized negation",
                )
            )

    for source_marker, expected_english in _DIRECTIONS.get(source_language, {}).items():
        if source_marker in source_text.casefold() and expected_english not in lowered_translation:
            issues.append(
                QualityIssue(
                    "direction",
                    "critical",
                    source_marker,
                    f"expected English direction {expected_english!r}",
                )
            )

    for term in required_terms:
        if term.casefold() in source_text.casefold() and term.casefold() not in lowered_translation:
            issues.append(
                QualityIssue(
                    "terminology",
                    "high",
                    term,
                    f"required term {term!r} is not preserved",
                )
            )
    source_sentences = len(_SENTENCE_BOUNDARY.findall(source_text))
    translated_sentences = len(_SENTENCE_BOUNDARY.findall(translated_text))
    if source_sentences >= 3 and translated_sentences < source_sentences - 1:
        issues.append(
            QualityIssue(
                "completeness",
                "critical",
                f"{source_sentences} source clauses",
                f"English has only {translated_sentences} sentence boundaries",
            )
        )
    if source_language in _SPACE_TOKEN_LANGUAGES:
        source_words = re.findall(r"\w+", source_text, flags=re.UNICODE)
        translated_words = re.findall(r"[A-Za-z0-9']+", translated_text)
        if len(source_words) >= 10 and len(translated_words) / len(source_words) < 0.45:
            issues.append(
                QualityIssue(
                    "completeness",
                    "critical",
                    f"{len(source_words)} source words",
                    f"English retains only {len(translated_words)} word-like units",
                )
            )
    if _repetition_loop(translated_text):
        issues.append(
            QualityIssue(
                "repetition",
                "critical",
                translated_text[:120],
                "English output contains a probable decoder loop",
            )
        )
    return TranslationQualityReport(
        passed=not any(issue.severity == "critical" for issue in issues),
        issues=tuple(issues),
        checked_categories=(
            "negation",
            "numbers",
            "percentages",
            "currency",
            "directions",
            "terminology",
            "completeness",
            "repetition",
        ),
    )
