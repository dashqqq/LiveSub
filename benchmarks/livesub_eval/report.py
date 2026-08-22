"""Aggregate model predictions into an evidence-bearing scorecard."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .corpus import CorpusCase, validate_corpus
from .metrics import (
    add_error_counts,
    character_error_counts,
    comet_scores,
    critical_error_report,
    duplicate_rate,
    percentile,
    repetition_loop,
    sacrebleu_scores,
    word_error_counts,
)


def load_predictions(paths: Iterable[Path]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(f"invalid JSONL {path}:{line_number}: {error}") from error
                if value.get("schema_version") != 1:
                    raise ValueError(f"unsupported prediction schema at {path}:{line_number}")
                values.append(value)
    return values


def build_report(cases: list[CorpusCase], predictions: list[dict[str, Any]]) -> dict[str, Any]:
    case_by_id = {case.case_id: case for case in cases}
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    unknown_cases: list[str] = []
    for prediction in predictions:
        case_id = str(prediction.get("case_id", ""))
        case = case_by_id.get(case_id)
        if case is None:
            unknown_cases.append(case_id)
            continue
        groups[(case.language, str(prediction["engine_id"]), str(prediction.get("route", "source_asr")))].append(prediction)

    scorecards: list[dict[str, Any]] = []
    for (language, engine_id, route), values in sorted(groups.items()):
        reviewed_pairs: list[tuple[CorpusCase, dict[str, Any]]] = []
        for value in values:
            case = case_by_id[str(value["case_id"])]
            if case.approved:
                reviewed_pairs.append((case, value))

        wers = [word_error_counts(case.source_text or "", str(value.get("source_text", ""))) for case, value in reviewed_pairs if value.get("source_text") is not None]
        cers = [character_error_counts(case.source_text or "", str(value.get("source_text", ""))) for case, value in reviewed_pairs if value.get("source_text") is not None]
        translation_pairs = [
            (case, value)
            for case, value in reviewed_pairs
            if value.get("translation_text") is not None
        ]
        critical = [
            critical_error_report(
                case.semantic_english or "",
                str(value.get("translation_text", "")),
                case.annotations,
            )
            for case, value in translation_pairs
        ]
        sources = [case.source_text or "" for case, _ in translation_pairs]
        references = [case.semantic_english or "" for case, _ in translation_pairs]
        hypotheses = [str(value.get("translation_text", "")) for _, value in translation_pairs]
        latency_values: list[float] = []
        for value in values:
            segment_latencies = value.get("metadata", {}).get("segment_latencies_ms")
            if isinstance(segment_latencies, list) and segment_latencies:
                latency_values.extend(float(item) for item in segment_latencies)
            elif value.get("latency_ms") is not None:
                latency_values.append(float(value["latency_ms"]))
        rtf_values = [float(value["rtf"]) for value in values if value.get("rtf") is not None]
        memory_values = [float(value["memory_mb"]) for value in values if value.get("memory_mb") is not None]
        vram_values = [float(value["vram_mb"]) for value in values if value.get("vram_mb") is not None]
        lid_values = [
            value
            for value in values
            if value.get("detected_language")
            and not value.get("metadata", {}).get("language_forced", False)
        ]
        stream_texts = [str(value.get("display_text", "")) for value in values if value.get("display_text")]
        decoder_loop_flags = [
            bool(segment.get("decoder_loop"))
            or bool(segment.get("source_decoder_loop"))
            or repetition_loop(
                str(
                    segment.get("translation_text")
                    or segment.get("text")
                    or segment.get("source_text")
                    or ""
                )
            )
            for value in values
            for segment in value.get("metadata", {}).get("segments", [])
        ]
        runtime_quality_reports = [
            report
            for value in values
            for segment in value.get("metadata", {}).get("segments", [])
            for report in (
                segment.get("quality_final") or segment.get("translation_quality"),
            )
            if isinstance(report, dict)
        ]
        runtime_quality_failures = sum(
            not bool(report.get("passed", False))
            for report in runtime_quality_reports
        )
        scorecards.append(
            {
                "language": language,
                "engine_id": engine_id,
                "route": route,
                "predictions": len(values),
                "reviewed_predictions": len(reviewed_pairs),
                "asr": {
                    "wer": add_error_counts(wers).to_dict() if wers else None,
                    "cer": add_error_counts(cers).to_dict() if cers else None,
                    "lid_accuracy": (
                        sum(str(value["detected_language"]) == language for value in lid_values)
                        / len(lid_values)
                        if lid_values
                        else None
                    ),
                },
                "translation": {
                    **sacrebleu_scores(references, hypotheses),
                    "comet": comet_scores(sources, references, hypotheses),
                    "critical_errors": (
                        sum(item["errors"] for item in critical) if critical else None
                    ),
                    "critical_cases_failed": (
                        sum(not item["passed"] for item in critical) if critical else None
                    ),
                    "reviewed_pairs": len(translation_pairs),
                    # These conservative checks operate on model source text,
                    # so they remain useful before human gold exists. They are
                    # kept separate from corpus-backed critical-error metrics.
                    "runtime_quality_segments": len(runtime_quality_reports),
                    "runtime_quality_segments_failed": (
                        runtime_quality_failures if runtime_quality_reports else None
                    ),
                    "runtime_quality_failure_rate": (
                        runtime_quality_failures / len(runtime_quality_reports)
                        if runtime_quality_reports
                        else None
                    ),
                },
                "live": {
                    "latency_p50_ms": percentile(latency_values, 0.50),
                    "latency_p95_ms": percentile(latency_values, 0.95),
                    "rtf_mean": sum(rtf_values) / len(rtf_values) if rtf_values else None,
                    "rtf_p95": percentile(rtf_values, 0.95),
                    "memory_peak_mb": max(memory_values) if memory_values else None,
                    "vram_peak_mb": max(vram_values) if vram_values else None,
                    "duplicate_rate": duplicate_rate(stream_texts),
                    "repetition_loops": sum(repetition_loop(text) for text in stream_texts),
                    "decoder_loop_rate": (
                        sum(decoder_loop_flags) / len(decoder_loop_flags)
                        if decoder_loop_flags
                        else None
                    ),
                    "hallucination_rate": None,
                },
                "selection_eligible": bool(reviewed_pairs)
                and len(reviewed_pairs) == len(values)
                and not any(value.get("error") for value in values),
            }
        )
    return {
        "schema_version": 1,
        "corpus": validate_corpus(cases),
        "unknown_prediction_case_ids": sorted(set(unknown_cases)),
        "scorecards": scorecards,
        "selection_ready": validate_corpus(cases)["ready"]
        and bool(scorecards)
        and all(card["selection_eligible"] for card in scorecards),
        "notice": "Missing metrics are null, never estimated or fabricated.",
    }


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# LiveSub accuracy scorecard",
        "",
        f"Selection ready: **{'YES' if report['selection_ready'] else 'NO'}**",
        "",
        "Missing values are shown as `N/A`; they are never inferred from model claims.",
        "",
    ]
    for language in ("ru", "ja", "hi"):
        lines.extend([f"## {language}", ""])
        cards = [item for item in report["scorecards"] if item["language"] == language]
        if not cards:
            lines.extend(["No prediction records.", ""])
            continue
        lines.extend(
            [
                "| Engine / route | WER | CER | LID | chrF++ | Gold critical | Runtime QA | Loops | p50 | p95 | RTF | Eligible |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|",
            ]
        )
        for card in cards:
            asr = card["asr"]
            translation = card["translation"]
            live = card["live"]

            def value(item: Any, suffix: str = "", scale: float = 1.0) -> str:
                return "N/A" if item is None else f"{float(item) * scale:.3f}{suffix}"

            wer = asr["wer"]["rate"] if asr["wer"] else None
            cer = asr["cer"]["rate"] if asr["cer"] else None
            lines.append(
                "| {engine} / {route} | {wer} | {cer} | {lid} | {chrf} | {critical} | {runtime_qa} | {loops} | {p50} | {p95} | {rtf} | {eligible} |".format(
                    engine=card["engine_id"],
                    route=card["route"],
                    wer=value(wer),
                    cer=value(cer),
                    lid=value(asr["lid_accuracy"]),
                    chrf=value(translation.get("chrf_pp")),
                    critical=(
                        "N/A"
                        if translation["critical_errors"] is None
                        else translation["critical_errors"]
                    ),
                    runtime_qa=(
                        "N/A"
                        if translation["runtime_quality_segments_failed"] is None
                        else f"{translation['runtime_quality_segments_failed']}/{translation['runtime_quality_segments']}"
                    ),
                    loops=(
                        "N/A"
                        if live["decoder_loop_rate"] is None
                        else f"{live['decoder_loop_rate']:.3f}"
                    ),
                    p50=value(live["latency_p50_ms"], " ms"),
                    p95=value(live["latency_p95_ms"], " ms"),
                    rtf=value(live["rtf_mean"]),
                    eligible="YES" if card["selection_eligible"] else "NO",
                )
            )
        lines.append("")
    lines.extend(["## Corpus gates", ""])
    for language, status in report["corpus"]["languages"].items():
        lines.append(
            f"- {language}: {status['human_approved_cases']}/{status['cases']} human-approved; "
            f"missing tags: {', '.join(status['missing_required_tags']) or 'none'}; "
            f"ready: {'YES' if status['ready'] else 'NO'}"
        )
    lines.append("")
    return "\n".join(lines)
