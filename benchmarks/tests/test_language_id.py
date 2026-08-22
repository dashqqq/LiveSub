from __future__ import annotations

import sys
import unittest
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[2]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from ai_worker.language_id import LanguageEvidenceAccumulator


class LanguageEvidenceTests(unittest.TestCase):
    def test_substantive_high_confidence_speech_locks_immediately(self) -> None:
        tracker = LanguageEvidenceAccumulator()
        decision = tracker.observe("ru", 0.95, evidence_audio_ms=3_200)
        self.assertTrue(decision.locked)
        self.assertEqual(decision.language, "ru")

    def test_short_speech_requires_repeated_evidence(self) -> None:
        tracker = LanguageEvidenceAccumulator()
        self.assertFalse(
            tracker.observe("ja", 0.75, evidence_audio_ms=900).locked
        )
        self.assertTrue(
            tracker.observe("ja", 0.78, evidence_audio_ms=1_100).locked
        )

    def test_one_contradiction_does_not_flip_but_repeated_evidence_does(self) -> None:
        tracker = LanguageEvidenceAccumulator()
        tracker.observe("hi", 0.96, evidence_audio_ms=4_000)
        first = tracker.observe("en", 0.91, evidence_audio_ms=4_000)
        self.assertEqual(first.language, "hi")
        self.assertFalse(first.changed_from)
        second = tracker.observe("en", 0.92, evidence_audio_ms=4_000)
        self.assertEqual(second.changed_from, "hi")
        self.assertEqual(second.language, "en")

    def test_reset_returns_previous_lock(self) -> None:
        tracker = LanguageEvidenceAccumulator()
        tracker.observe("ru", 0.99, evidence_audio_ms=4_000)
        self.assertEqual(tracker.reset(), "ru")
        self.assertIsNone(tracker.current())


if __name__ == "__main__":
    unittest.main()
