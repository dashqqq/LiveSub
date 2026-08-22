#!/usr/bin/env python3
"""Validate golden corpora and score model prediction JSONL files."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from livesub_eval.corpus import load_corpus, validate_corpus
from livesub_eval.report import build_report, load_predictions, markdown_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("validate", "score"))
    parser.add_argument(
        "--corpus-root", type=Path, default=SCRIPT_ROOT / "corpora"
    )
    parser.add_argument("--predictions", type=Path, action="append", default=[])
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-markdown", type=Path)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="return nonzero until all default-language golden gates pass",
    )
    args = parser.parse_args()

    cases = load_corpus(args.corpus_root)
    if args.command == "validate":
        report = validate_corpus(cases)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        predictions = load_predictions(args.predictions)
        report = build_report(cases, predictions)
        rendered = markdown_report(report)
        print(rendered)
        if args.output_markdown:
            args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
            args.output_markdown.write_text(rendered, encoding="utf-8")

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return 2 if args.strict and not report["ready" if args.command == "validate" else "selection_ready"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
