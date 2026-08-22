from __future__ import annotations

import sys
import unittest
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[2]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from ai_worker.translation.consistency import SessionGlossary, TranslationMemory
from ai_worker.translation.quality import check_translation_quality


class TranslationQualityTests(unittest.TestCase):
    def test_hindi_number_negation_direction_failures(self) -> None:
        result = check_translation_quality(
            "बाएं 15 दुश्मन नहीं हैं",
            "There are 50 enemies on the right.",
            source_language="hi",
        )
        categories = {issue.category for issue in result.issues}
        self.assertFalse(result.passed)
        self.assertEqual(categories, {"number", "negation", "direction"})

    def test_spoken_number_equivalents_do_not_false_alarm(self) -> None:
        cases = (
            ("ru", "Слева пятнадцать врагов.", "There are fifteen enemies on the left."),
            ("ja", "右に五十人いる。", "There are 50 people on the right."),
            ("hi", "बाएँ एक सौ पचास लोग हैं।", "There are one hundred and fifty people on the left."),
            ("hi", "Abhi pandrah players hain.", "There are 15 players now."),
        )
        for language, source, translation in cases:
            with self.subTest(language=language, source=source):
                result = check_translation_quality(
                    source, translation, source_language=language
                )
                self.assertNotIn("number", {issue.category for issue in result.issues})

    def test_percentage_and_currency_loss_are_critical(self) -> None:
        result = check_translation_quality(
            "Цена 50 рублей, скидка 15 процентов.",
            "The price is fifty with a fifteen discount.",
            source_language="ru",
        )
        categories = {issue.category for issue in result.issues}
        self.assertIn("percentage", categories)
        self.assertIn("currency", categories)
        self.assertFalse(result.passed)

    def test_session_glossary_requires_repeated_confidence(self) -> None:
        glossary = SessionGlossary()
        self.assertFalse(glossary.observe("Tarkov", 0.95))
        self.assertTrue(glossary.observe("Tarkov", 0.90))
        self.assertEqual(glossary.locked_terms(), ("Tarkov",))
        self.assertFalse(glossary.observe("Tarkoff", 0.20))
        self.assertNotIn("Tarkoff", glossary.locked_terms())

    def test_translation_memory_is_exact_and_context_scoped(self) -> None:
        memory = TranslationMemory()
        self.assertTrue(
            memory.remember(
                "Слева один",
                "There is one on the left.",
                source_language="ru",
                context_key="game-a",
                confidence=0.9,
            )
        )
        self.assertIsNotNone(
            memory.lookup("Слева один", source_language="ru", context_key="game-a")
        )
        self.assertIsNone(
            memory.lookup("Слева двое", source_language="ru", context_key="game-a")
        )
        self.assertIsNone(
            memory.lookup("Слева один", source_language="ru", context_key="game-b")
        )

    def test_summarization_like_clause_loss_is_critical(self) -> None:
        result = check_translation_quality(
            "Здравствуйте. Добрый день. Меня зовут Джоан, а вас?",
            "Hello.",
            source_language="ru",
        )
        self.assertFalse(result.passed)
        self.assertIn("completeness", {issue.category for issue in result.issues})

    def test_translation_decoder_loop_is_critical(self) -> None:
        result = check_translation_quality(
            "श्री शिव मंगल सिंह सुमन द्वारा रचित कविता",
            "Shiva Shiva Shiva Shiva Shiva Shiva Shiva Shiva",
            source_language="hi",
        )
        self.assertFalse(result.passed)
        self.assertIn("repetition", {issue.category for issue in result.issues})


if __name__ == "__main__":
    unittest.main()
