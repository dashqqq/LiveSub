from __future__ import annotations

import unittest
import sys
from pathlib import Path

BENCHMARK_ROOT = Path(__file__).resolve().parents[1]
if str(BENCHMARK_ROOT) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_ROOT))

from livesub_eval.metrics import (
    character_error_counts,
    critical_error_report,
    percentile,
    repetition_loop,
    word_error_counts,
)


class MetricTests(unittest.TestCase):
    def test_word_error_counts_keep_operations(self) -> None:
        value = word_error_counts(
            "We have two enemies on the left",
            "We have enemies on the right",
        )
        self.assertEqual(value.reference_units, 7)
        self.assertEqual(value.errors, 2)
        self.assertAlmostEqual(value.rate or 0.0, 2 / 7)

    def test_character_error_counts_handle_unspaced_japanese(self) -> None:
        value = character_error_counts("左に二人います", "左に二人います")
        self.assertEqual(value.errors, 0)
        self.assertEqual(value.reference_units, 7)

    def test_critical_errors_detect_meaning_changes(self) -> None:
        value = critical_error_report(
            "We don't have 15 enemies on the left near Discord at 10:30.",
            "We have 50 enemies on the right near Discard at 10:30.",
            {"names": ["Discord"]},
        )
        self.assertEqual(value["errors"], 4)
        self.assertIn("don't", value["categories"]["negation"]["missing"])
        self.assertIn("15", value["categories"]["numbers"]["missing"])
        self.assertIn("left", value["categories"]["directions"]["missing"])
        self.assertIn("Discord", value["categories"]["names"]["missing"])

    def test_percentile_interpolates(self) -> None:
        self.assertEqual(percentile([1, 2, 3, 4], 0.5), 2.5)
        self.assertAlmostEqual(percentile([1, 2, 3, 4], 0.95) or 0.0, 3.85)

    def test_repetition_loop(self) -> None:
        self.assertTrue(repetition_loop("thank you thank you thank you thank you"))
        self.assertTrue(repetition_loop("ट्ट्ट्ट्ट्ट्ट्ट्ट्ट्ट्ट्ट्ट्ट्ट्ट्ट्ट्ट्ट"))
        self.assertFalse(repetition_loop("we are going into the building from the left"))


if __name__ == "__main__":
    unittest.main()
