"""Golden-corpus loading and acceptance validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


REQUIRED_TAGS = {
    "clean",
    "livestream",
    "gaming",
    "casual",
    "fast",
    "code_switching",
    "names",
    "numbers",
    "music",
    "noise",
    "multiple_speakers",
}
DEFAULT_LANGUAGES = {"ru", "ja", "hi"}


@dataclass(frozen=True)
class CorpusCase:
    case_id: str
    language: str
    audio_path: Path
    duration_ms: int | None
    tags: tuple[str, ...]
    gold_status: str
    source_text: str | None
    semantic_english: str | None
    annotations: dict[str, Any]
    provenance: dict[str, Any]

    @property
    def approved(self) -> bool:
        return (
            self.gold_status == "human_approved"
            and bool(self.source_text)
            and bool(self.semantic_english)
        )


def load_corpus(root: Path) -> list[CorpusCase]:
    cases: list[CorpusCase] = []
    for manifest_path in sorted(root.glob("*/manifest.json")):
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
        if document.get("schema_version") != 1:
            raise ValueError(f"unsupported corpus schema in {manifest_path}")
        language = str(document["language"])
        for raw in document.get("cases", []):
            audio_path = (manifest_path.parent / str(raw["audio"])).resolve()
            cases.append(
                CorpusCase(
                    case_id=str(raw["id"]),
                    language=language,
                    audio_path=audio_path,
                    duration_ms=(
                        int(raw["duration_ms"])
                        if raw.get("duration_ms") is not None
                        else None
                    ),
                    tags=tuple(str(value) for value in raw.get("tags", [])),
                    gold_status=str(raw.get("gold_status", "pending_human_review")),
                    source_text=raw.get("source_text"),
                    semantic_english=raw.get("semantic_english"),
                    annotations=dict(raw.get("annotations", {})),
                    provenance=dict(raw.get("provenance", {})),
                )
            )
    identifiers = [case.case_id for case in cases]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("golden corpus case IDs are not unique")
    return cases


def validate_corpus(cases: Iterable[CorpusCase]) -> dict[str, Any]:
    items = list(cases)
    languages: dict[str, dict[str, Any]] = {}
    for language in sorted(DEFAULT_LANGUAGES | {item.language for item in items}):
        relevant = [item for item in items if item.language == language]
        tags = {tag for item in relevant for tag in item.tags}
        missing_audio = [str(item.audio_path) for item in relevant if not item.audio_path.is_file()]
        approved = [item for item in relevant if item.approved]
        languages[language] = {
            "cases": len(relevant),
            "human_approved_cases": len(approved),
            "pending_cases": len(relevant) - len(approved),
            "tags": sorted(tags),
            "missing_required_tags": sorted(REQUIRED_TAGS - tags),
            "missing_audio": missing_audio,
            "ready": bool(approved)
            and not (REQUIRED_TAGS - tags)
            and not missing_audio
            and len(approved) == len(relevant),
        }
    return {
        "schema_version": 1,
        "languages": languages,
        "ready": all(value["ready"] for key, value in languages.items() if key in DEFAULT_LANGUAGES),
    }
