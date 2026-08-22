#!/usr/bin/env python3
"""Run a pinned local MT candidate over source-ASR benchmark records.

Input must be JSONL emitted by ``run_asr.py --route source_asr``. The output
preserves the measured ASR time and adds measured MT time, allowing Path B to be
compared against direct Whisper translation without substituting gold text for
recognizer output.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback
from pathlib import Path
from typing import Any

BENCHMARK_PACKAGE_ROOT = os.environ.get("LIVESUB_BENCHMARK_PACKAGE_ROOT")
if BENCHMARK_PACKAGE_ROOT:
    package_root = Path(BENCHMARK_PACKAGE_ROOT).resolve()
    if not package_root.is_dir():
        raise RuntimeError(f"benchmark package root does not exist: {package_root}")
    sys.path.insert(0, str(package_root))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WORKSPACE = Path(__file__).resolve().parents[1]
BENCHMARK_ROOT = Path(__file__).resolve().parent
for import_root in (WORKSPACE, BENCHMARK_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from ai_worker.translation import TransformersMTConfig, TransformersTranslationEngine
from ai_worker.translation.quality import check_translation_quality
from livesub_eval.corpus import CorpusCase, load_corpus
from livesub_eval.metrics import percentile
from run_asr import process_memory_mb, process_vram_mb


ENGINE_RECIPES: dict[str, dict[str, Any]] = {
    "opus-mt-ru-en": {
        "repository": "Helsinki-NLP/opus-mt-ru-en",
        "sources": ("ru",),
        "model_family": "generic",
    },
    "opus-mt-ja-en": {
        "repository": "Helsinki-NLP/opus-mt-ja-en",
        "sources": ("ja",),
        "model_family": "generic",
    },
    "opus-mt-es-en": {
        "repository": "Helsinki-NLP/opus-mt-es-en",
        "sources": ("es",),
        "model_family": "generic",
    },
    "m2m100-418m": {
        "repository": "facebook/m2m100_418M",
        "sources": ("ru", "ja", "hi", "es"),
        "model_family": "m2m100",
        "source_language_codes": (("ru", "ru"), ("ja", "ja"), ("hi", "hi"), ("es", "es")),
        "target_language_code": "en",
    },
}


def load_source_predictions(path: Path) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if value.get("schema_version") != 1:
                raise ValueError(f"unsupported record at {path}:{line_number}")
            if value.get("route") != "source_asr":
                raise ValueError(f"record is not source ASR at {path}:{line_number}")
            values.append(value)
    return values


def create_engine(args: argparse.Namespace) -> TransformersTranslationEngine:
    recipe = ENGINE_RECIPES[args.engine]
    if not re.fullmatch(r"[0-9a-f]{40}", args.model_revision):
        raise ValueError("--model-revision must be an exact 40-character commit")
    return TransformersTranslationEngine(
        TransformersMTConfig(
            engine_id=args.engine,
            model_id=f"{recipe['repository']}@{args.model_revision}",
            model_path=str(args.model_path),
            source_languages=recipe["sources"],
            device=args.device,
            dtype=args.dtype,
            beam_size=args.beam_size,
            model_family=recipe["model_family"],
            source_language_codes=recipe.get("source_language_codes", ()),
            target_language_code=recipe.get("target_language_code", ""),
        )
    )


def prediction_for(
    engine: TransformersTranslationEngine,
    source: dict[str, Any],
    case: CorpusCase,
) -> dict[str, Any]:
    source_text = str(source.get("source_text") or "").strip()
    if source.get("error"):
        raise ValueError(f"source ASR failed: {source['error']}")
    if not source_text:
        raise ValueError("source ASR record has no source text")
    required_terms = tuple(
        str(item)
        for key in ("names", "products", "critical_terms")
        for item in case.annotations.get(key, [])
    )
    source_segments = source.get("metadata", {}).get("segments")
    if not isinstance(source_segments, list) or not source_segments:
        source_segments = [
            {
                "text": source_text,
                "inference_ms": float(source.get("latency_ms") or 0),
                "audio_ms": float(source.get("metadata", {}).get("audio_ms") or 0),
                "audio_start_ms": 0,
                "audio_end_ms": float(source.get("metadata", {}).get("audio_ms") or 0),
            }
        ]
    memory_before = process_memory_mb()
    vram_before, scope_before = process_vram_mb()
    results = []
    translated_segments = []
    context = ""
    for source_segment in source_segments:
        segment_text = str(source_segment.get("text") or "").strip()
        if not segment_text:
            continue
        result = engine.translate(
            segment_text,
            source_language=case.language,
            target_language="en",
            context=context,
            glossary=required_terms,
        )
        results.append(result)
        quality = check_translation_quality(
            segment_text,
            result.translated_text,
            source_language=case.language,
            required_terms=required_terms,
        )
        asr_latency = float(source_segment.get("inference_ms") or 0)
        translated_segments.append(
            {
                "audio_start_ms": source_segment.get("audio_start_ms"),
                "audio_end_ms": source_segment.get("audio_end_ms"),
                "audio_ms": float(source_segment.get("audio_ms") or 0),
                "source_text": segment_text,
                "translation_text": result.translated_text,
                "asr_latency_ms": asr_latency,
                "translation_latency_ms": result.inference_ms,
                "pipeline_latency_ms": asr_latency + result.inference_ms,
                "translation_quality": quality.to_dict(),
                "source_decoder_loop": bool(source_segment.get("decoder_loop")),
            }
        )
        if result.translated_text:
            context = (context + " " + result.translated_text).strip()[-480:]
    if not results:
        raise ValueError("source ASR record has no translatable speech segments")
    result = results[-1]
    memory_after = process_memory_mb()
    vram_after, scope_after = process_vram_mb()
    translation_text = " ".join(
        item["translation_text"].strip()
        for item in translated_segments
        if item["translation_text"].strip()
    )
    pipeline_latencies = [item["pipeline_latency_ms"] for item in translated_segments]
    translation_latencies = [item["translation_latency_ms"] for item in translated_segments]
    asr_latencies = [item["asr_latency_ms"] for item in translated_segments]
    audio_ms = sum(item["audio_ms"] for item in translated_segments)
    total_pipeline_ms = sum(pipeline_latencies)
    memory_values = [value for value in (memory_before, memory_after) if value is not None]
    vram_values = [value for value in (vram_before, vram_after) if value is not None]
    return {
        "schema_version": 1,
        "case_id": case.case_id,
        "engine_id": f"{source['engine_id']}+{result.engine_id}",
        "model_id": f"{source['model_id']}+{result.model_id}",
        "route": "asr_then_mt",
        "detected_language": source.get("detected_language"),
        "language_confidence": source.get("language_confidence"),
        "source_text": source_text,
        "translation_text": translation_text,
        "display_text": None,
        "latency_ms": percentile(pipeline_latencies, 0.50),
        "rtf": total_pipeline_ms / audio_ms if audio_ms > 0 else None,
        "memory_mb": max(memory_values) if memory_values else None,
        "vram_mb": max(vram_values) if vram_values else None,
        "error": None,
        "metadata": {
            "asr_engine_id": source["engine_id"],
            "asr_model_id": source["model_id"],
            "language_forced": bool(
                source.get("metadata", {}).get("language_forced", False)
            ),
            "asr_latency_ms": sum(asr_latencies),
            "translation_engine_id": result.engine_id,
            "translation_model_id": result.model_id,
            "translation_latency_ms": sum(translation_latencies),
            "audio_ms": audio_ms,
            "total_pipeline_ms": total_pipeline_ms,
            "segment_latencies_ms": pipeline_latencies,
            "segment_latency_p50_ms": percentile(pipeline_latencies, 0.50),
            "segment_latency_p95_ms": percentile(pipeline_latencies, 0.95),
            "translation_segment_latencies_ms": translation_latencies,
            "segments": translated_segments,
            "quality_segments_failed": sum(
                not item["translation_quality"]["passed"] for item in translated_segments
            ),
            "decoder_loop_segments": sum(
                item["source_decoder_loop"] for item in translated_segments
            ),
            "vram_measurement_scope": scope_after or scope_before,
            **dict(result.metadata),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--engine", choices=tuple(ENGINE_RECIPES), required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--corpus-root", type=Path, default=BENCHMARK_ROOT / "corpora")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--dtype", choices=("auto", "float16", "bfloat16", "float32"), default="auto")
    parser.add_argument("--beam-size", type=int, default=5)
    parser.add_argument("--skip-warmup", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    cases = {case.case_id: case for case in load_corpus(args.corpus_root)}
    sources = load_source_predictions(args.input)
    unknown = sorted({str(item.get("case_id", "")) for item in sources} - set(cases))
    if unknown:
        raise ValueError(f"unknown case IDs: {', '.join(unknown)}")
    engine = create_engine(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not args.skip_warmup:
        engine.warmup()
    try:
        with args.output.open("a", encoding="utf-8", buffering=1) as handle:
            for source in sources:
                case = cases[str(source["case_id"])]
                try:
                    value = prediction_for(engine, source, case)
                except Exception as error:
                    value = {
                        "schema_version": 1,
                        "case_id": case.case_id,
                        "engine_id": f"{source.get('engine_id', 'unknown')}+{args.engine}",
                        "model_id": f"{source.get('model_id', 'unknown')}+{args.model_revision}",
                        "route": "asr_then_mt",
                        "error": f"{type(error).__name__}: {error}",
                        "metadata": {"traceback": traceback.format_exc()},
                    }
                    if args.fail_fast:
                        raise
                handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
                if not args.quiet:
                    print(json.dumps(value, ensure_ascii=False, indent=2))
    finally:
        engine.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
