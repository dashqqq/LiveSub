from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

WORKSPACE = Path(__file__).resolve().parents[2]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from ai_worker.worker import AsrLoop, InferenceJob, LatestJobQueue, WorkerConfig


class _Emitter:
    def __init__(self) -> None:
        self.events = []

    def send(self, _event_type: str, **_fields) -> None:
        self.events.append((_event_type, _fields))


class WorkerConfigTests(unittest.TestCase):
    def test_model_download_is_fail_closed_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = WorkerConfig(model="not-installed", model_dir=temporary)
            loop = AsrLoop(config, LatestJobQueue(), _Emitter())
            with self.assertRaisesRegex(RuntimeError, "is not installed"):
                loop._load_model()

    def test_development_download_requires_explicit_protocol_flag(self) -> None:
        default = WorkerConfig.from_message({"preset": "balanced"})
        opted_in = WorkerConfig.from_message({"allow_model_download": True})
        self.assertFalse(default.allow_model_download)
        self.assertTrue(opted_in.allow_model_download)

    def test_semantic_failure_selects_better_bounded_verification(self) -> None:
        class Model:
            def __init__(self) -> None:
                self.outputs = iter(
                    (
                        "There are 50 enemies on the right.",
                        "There are not 15 enemies on the left.",
                    )
                )

            def transcribe(self, _audio, **_kwargs):
                segment = SimpleNamespace(
                    text=next(self.outputs),
                    avg_logprob=-0.1,
                    no_speech_prob=0.01,
                    compression_ratio=1.0,
                )
                return [segment], SimpleNamespace(language="hi")

        emitter = _Emitter()
        loop = AsrLoop(WorkerConfig(), LatestJobQueue(), emitter)
        loop._model = Model()
        loop._backend = "test"
        loop._detect_language = lambda _job: ("hi", 0.95, True)
        loop._transcribe_source_final = lambda _job, _language: (
            "बाएँ 15 दुश्मन नहीं हैं",
            1,
            -0.1,
            0.01,
            False,
        )
        loop._decode(
            InferenceJob(
                segment_id=1,
                revision=1,
                audio=np.zeros((16_000,), dtype=np.float32),
                audio_start_ms=0,
                audio_end_ms=1_000,
                audio_capture_end_unix_ms=1,
                is_final=True,
            )
        )
        transcript = next(fields for kind, fields in emitter.events if kind == "transcript")
        self.assertEqual(transcript["text"], "There are not 15 enemies on the left.")
        self.assertTrue(transcript["verification_attempted"])
        self.assertTrue(transcript["verification_selected"])
        self.assertTrue(transcript["quality_passed"])
        self.assertEqual(transcript["translation_engine"], "whisper-direct+verified-beam5")
        remembered = loop._translation_memory.lookup(
            "बाएँ 15 दुश्मन नहीं हैं", source_language="hi"
        )
        self.assertIsNotNone(remembered)
        self.assertEqual(
            remembered.translation, "There are not 15 enemies on the left."
        )

    def test_semantically_failed_translation_is_not_memorized(self) -> None:
        class Model:
            def transcribe(self, _audio, **_kwargs):
                segment = SimpleNamespace(
                    text="There are 50 enemies on the right.",
                    avg_logprob=-0.1,
                    no_speech_prob=0.01,
                    compression_ratio=1.0,
                )
                return [segment], SimpleNamespace(language="hi")

        emitter = _Emitter()
        loop = AsrLoop(WorkerConfig(), LatestJobQueue(), emitter)
        loop._model = Model()
        loop._backend = "test"
        loop._detect_language = lambda _job: ("hi", 0.95, True)
        loop._transcribe_source_final = lambda _job, _language: (
            "बाएँ 15 दुश्मन नहीं हैं",
            1,
            -0.1,
            0.01,
            False,
        )
        loop._decode(
            InferenceJob(
                segment_id=1,
                revision=1,
                audio=np.zeros((16_000,), dtype=np.float32),
                audio_start_ms=0,
                audio_end_ms=1_000,
                audio_capture_end_unix_ms=1,
                is_final=True,
            )
        )
        transcript = next(fields for kind, fields in emitter.events if kind == "transcript")
        self.assertTrue(transcript["verification_attempted"])
        self.assertFalse(transcript["verification_selected"])
        self.assertFalse(transcript["quality_passed"])
        self.assertIsNone(
            loop._translation_memory.lookup(
                "बाएँ 15 दुश्मन नहीं हैं", source_language="hi"
            )
        )


if __name__ == "__main__":
    unittest.main()
