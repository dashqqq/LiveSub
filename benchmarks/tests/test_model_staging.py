from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[2]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from ai_worker.language_packs import RegistryError
from tools.stage_model import (
    _allowed_file,
    existing_stage_is_valid,
    select_model,
    verify_registry_artifacts,
)


class ModelStagingTests(unittest.TestCase):
    def test_executable_repository_files_are_rejected(self) -> None:
        self.assertFalse(_allowed_file("modeling_custom.py"))
        self.assertFalse(_allowed_file("native/runtime.dll"))
        self.assertTrue(_allowed_file("model-00001-of-00002.safetensors"))
        self.assertTrue(_allowed_file("tokenizer.json"))

    def test_nonapproved_candidate_cannot_be_staged(self) -> None:
        registry = {
            "models": [
                {
                    "id": "blocked",
                    "status": "blocked_code_review",
                    "trust_remote_code": True,
                }
            ]
        }
        with self.assertRaisesRegex(RegistryError, "not eligible"):
            select_model(registry, "blocked")

    def test_existing_stage_hashes_are_reverified(self) -> None:
        model = {
            "repository": "test/model",
            "revision": "a" * 40,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "weights.safetensors"
            artifact.write_bytes(b"verified")
            provenance = {
                "repository": model["repository"],
                "revision": model["revision"],
                "artifacts": [
                    {
                        "path": artifact.name,
                        "size_bytes": artifact.stat().st_size,
                        "sha256": hashlib.sha256(b"verified").hexdigest(),
                    }
                ],
            }
            (root / ".livesub-provenance.json").write_text(
                json.dumps(provenance), encoding="utf-8"
            )
            self.assertTrue(existing_stage_is_valid(root, model))
            artifact.write_bytes(b"tampered")
            self.assertFalse(existing_stage_is_valid(root, model))

    def test_registry_hash_mismatch_rejects_downloaded_artifact(self) -> None:
        model = {
            "artifacts": [
                {
                    "path": "weights.safetensors",
                    "size_bytes": 8,
                    "sha256": hashlib.sha256(b"expected").hexdigest(),
                }
            ]
        }
        actual = [
            {
                "path": "weights.safetensors",
                "size_bytes": 8,
                "sha256": hashlib.sha256(b"tampered").hexdigest(),
            }
        ]
        with self.assertRaisesRegex(RegistryError, "mismatch"):
            verify_registry_artifacts(model, actual)


if __name__ == "__main__":
    unittest.main()
