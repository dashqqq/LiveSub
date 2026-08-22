from __future__ import annotations

import tempfile
import unittest
import sys
from pathlib import Path

BENCHMARK_ROOT = Path(__file__).resolve().parents[1]
if str(BENCHMARK_ROOT) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_ROOT))

from livesub_eval.corpus import CorpusCase, validate_corpus
from livesub_eval.report import build_report


class ReportTests(unittest.TestCase):
    def test_pending_gold_never_produces_fake_accuracy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "sample.wav"
            audio.write_bytes(b"fixture")
            case = CorpusCase(
                case_id="ru-test",
                language="ru",
                audio_path=audio,
                duration_ms=1000,
                tags=("clean",),
                gold_status="pending_human_review",
                source_text=None,
                semantic_english=None,
                annotations={},
                provenance={},
            )
            prediction = {
                "schema_version": 1,
                "case_id": "ru-test",
                "engine_id": "candidate",
                "model_id": "candidate@revision",
                "route": "source_asr",
                "detected_language": "ru",
                "source_text": "unreviewed model output",
                "latency_ms": 100,
                "rtf": 0.1,
            }
            report = build_report([case], [prediction])
            self.assertFalse(report["selection_ready"])
            self.assertIsNone(report["scorecards"][0]["asr"]["wer"])
            self.assertIsNone(
                report["scorecards"][0]["translation"]["critical_errors"]
            )
            self.assertFalse(report["scorecards"][0]["selection_eligible"])

    def test_default_languages_are_not_ready_without_coverage(self) -> None:
        status = validate_corpus([])
        self.assertFalse(status["ready"])
        self.assertFalse(status["languages"]["hi"]["ready"])

    def test_runtime_quality_failures_are_separate_from_missing_gold(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "sample.wav"
            audio.write_bytes(b"fixture")
            case = CorpusCase(
                case_id="hi-runtime",
                language="hi",
                audio_path=audio,
                duration_ms=1000,
                tags=("clean",),
                gold_status="pending_human_review",
                source_text=None,
                semantic_english=None,
                annotations={},
                provenance={},
            )
            prediction = {
                "schema_version": 1,
                "case_id": "hi-runtime",
                "engine_id": "candidate",
                "route": "asr_then_mt",
                "rtf": 0.5,
                "metadata": {
                    "segments": [
                        {
                            "decoder_loop": False,
                            "translation_quality": {"passed": False},
                        },
                        {
                            "decoder_loop": True,
                            "translation_quality": {"passed": True},
                        },
                    ]
                },
            }
            card = build_report([case], [prediction])["scorecards"][0]
            self.assertIsNone(card["translation"]["critical_errors"])
            self.assertEqual(
                card["translation"]["runtime_quality_segments_failed"], 1
            )
            self.assertEqual(card["translation"]["runtime_quality_failure_rate"], 0.5)
            self.assertEqual(card["live"]["decoder_loop_rate"], 0.5)


if __name__ == "__main__":
    unittest.main()
