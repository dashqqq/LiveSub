from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

WORKSPACE = Path(__file__).resolve().parents[2]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from ai_worker.engines.whisper import (
    DIRECT_TRANSLATION_MAX_NEW_TOKENS,
    SOURCE_TRANSCRIPTION_MAX_NEW_TOKENS,
    FasterWhisperASREngine,
    WhisperEngineConfig,
)


class _RecordingModel:
    def __init__(self) -> None:
        self.kwargs: dict[str, object] = {}

    def transcribe(self, audio: np.ndarray, **kwargs: object):
        self.kwargs = kwargs
        segment = SimpleNamespace(
            text="translated text",
            avg_logprob=-0.2,
            no_speech_prob=0.1,
            compression_ratio=1.0,
            words=None,
            start=0.0,
            end=float(audio.size / 16_000),
        )
        info = SimpleNamespace(language="hi", language_probability=0.9)
        return iter((segment,)), info


def _engine() -> tuple[FasterWhisperASREngine, _RecordingModel]:
    engine = FasterWhisperASREngine.__new__(FasterWhisperASREngine)
    engine.config = WhisperEngineConfig(
        engine_id="test",
        model_id="test@revision",
        model_source="unused",
        model_dir="unused",
        final_beam_size=3,
    )
    engine.device = "cpu"
    engine.compute_type = "int8"
    model = _RecordingModel()
    engine._model = model
    return engine, model


class WhisperEnginePolicyTests(unittest.TestCase):
    def test_direct_translation_is_bounded_and_drops_english_context(self) -> None:
        engine, model = _engine()
        result = engine._transcribe(
            np.zeros((16_000,), dtype=np.float32),
            16_000,
            language="hi",
            context="unsafe prior English translation",
            glossary=("Discord",),
            is_final=True,
            task="translate",
        )
        self.assertEqual(model.kwargs["max_new_tokens"], DIRECT_TRANSLATION_MAX_NEW_TOKENS)
        self.assertEqual(model.kwargs["initial_prompt"], "Terminology: Discord")
        self.assertFalse(model.kwargs["word_timestamps"])
        self.assertEqual(result.metadata["timestamp_granularity"], "segment")
        self.assertEqual(len(result.timestamps), 1)

    def test_source_final_is_bounded_and_keeps_source_context(self) -> None:
        engine, model = _engine()
        engine._transcribe(
            np.zeros((16_000,), dtype=np.float32),
            16_000,
            language="ru",
            context="source context",
            glossary=(),
            is_final=True,
            task="transcribe",
        )
        self.assertEqual(model.kwargs["max_new_tokens"], SOURCE_TRANSCRIPTION_MAX_NEW_TOKENS)
        self.assertEqual(model.kwargs["initial_prompt"], "source context")
        self.assertEqual(model.kwargs["beam_size"], 3)

    def test_verification_translation_uses_explicit_stronger_beam(self) -> None:
        engine, model = _engine()
        result = engine.translate_final_with_beam(
            np.zeros((16_000,), dtype=np.float32),
            16_000,
            language="ja",
            beam_size=5,
            glossary=("Tarkov",),
        )
        self.assertEqual(model.kwargs["beam_size"], 5)
        self.assertEqual(result.metadata["beam_size"], 5)
        self.assertEqual(model.kwargs["initial_prompt"], "Terminology: Tarkov")


if __name__ == "__main__":
    unittest.main()
