from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

WORKSPACE = Path(__file__).resolve().parents[2]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from ai_worker.language_packs import (
    LanguagePackError,
    LanguagePackManager,
    RegistryError,
    VerifiedDownloadManager,
    load_registry,
    verify_pack,
)


def _write_test_pack(root: Path, version: str, payload: bytes = b"model-data") -> None:
    root.mkdir(parents=True)
    artifact = root / "models" / "weights.bin"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(payload)
    manifest = {
        "schema_version": 1,
        "language": "zz-Test",
        "display_name": "Test Language",
        "version": version,
        "status": "validated",
        "models": [
            {
                "owner": "Test Owner",
                "repository": "test/known-model",
                "revision": "a" * 40,
                "downloaded_at": "2026-08-22T12:00:00Z",
                "trust_remote_code": False,
                "license": {
                    "spdx": "MIT",
                    "commercial_use_allowed": True,
                    "redistribution_allowed": True,
                },
            }
        ],
        "license": {
            "commercial_use_allowed": True,
            "redistribution_allowed": True,
        },
        "artifacts": [
            {
                "path": "models/weights.bin",
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        ],
        "acceptance": {
            "status": "passed",
            "corpus_revision": "test-only",
            "completed_at": "2026-08-22T12:00:00Z",
        },
        "signature": {
            "algorithm": "ed25519",
            "key_id": "test-development-key",
            "status": "development_unsigned",
            "value": None,
        },
    }
    (root / "language-pack.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


class LanguagePackTests(unittest.TestCase):
    def test_curated_registry_fails_closed_in_production(self) -> None:
        path = WORKSPACE / "registry" / "language-registry.json"
        with self.assertRaisesRegex(RegistryError, "unsigned development"):
            load_registry(path, {})

    def test_curated_registry_is_explicitly_loadable_for_development(self) -> None:
        path = WORKSPACE / "registry" / "language-registry.json"
        document = load_registry(path, {}, allow_development_unsigned=True)
        self.assertFalse(document["production_ready"])
        self.assertTrue(all(not item["installable"] for item in document["languages"]))
        rejected = next(
            model for model in document["models"] if model["id"] == "nllb-200-distilled-600m"
        )
        self.assertFalse(rejected["license"]["commercial_use_allowed"])

    def test_production_registry_requires_pinned_artifacts(self) -> None:
        document = json.loads(
            (WORKSPACE / "registry" / "language-registry.json").read_text(
                encoding="utf-8"
            )
        )
        document["production_ready"] = True
        for model in document["models"]:
            model.pop("artifacts", None)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "registry.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(RegistryError, "no registry-pinned artifacts"):
                load_registry(path, {}, allow_development_unsigned=True)

    def test_pack_hash_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "pack"
            _write_test_pack(root, "1.0.0")
            (root / "models" / "weights.bin").write_bytes(b"tampered")
            manifest = json.loads((root / "language-pack.json").read_text(encoding="utf-8"))
            with self.assertRaisesRegex(LanguagePackError, "mismatch"):
                verify_pack(root, manifest, {}, allow_development_unsigned=True)

    def test_pack_rejects_unverified_extra_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "pack"
            _write_test_pack(root, "1.0.0")
            (root / "models" / "unlisted.py").write_text(
                "raise RuntimeError('must never execute')\n", encoding="utf-8"
            )
            manifest = json.loads((root / "language-pack.json").read_text(encoding="utf-8"))
            with self.assertRaisesRegex(LanguagePackError, "unverified files"):
                verify_pack(root, manifest, {}, allow_development_unsigned=True)

    def test_pack_rejects_non_integer_artifact_size(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "pack"
            _write_test_pack(root, "1.0.0")
            manifest = json.loads((root / "language-pack.json").read_text(encoding="utf-8"))
            manifest["artifacts"][0]["size_bytes"] = "10"
            with self.assertRaisesRegex(LanguagePackError, "invalid size"):
                verify_pack(root, manifest, {}, allow_development_unsigned=True)

    def test_install_update_and_verified_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app_data = Path(temporary) / "app-data"
            manager = LanguagePackManager(
                app_data,
                trusted_keys={},
                allow_development_unsigned=True,
            )
            first = manager.staging_root / "first"
            _write_test_pack(first, "1.0.0", b"known-good-one")
            installed = manager.install_from_staging(first)
            self.assertEqual(installed.version, "1.0.0")

            second = manager.staging_root / "second"
            _write_test_pack(second, "2.0.0", b"candidate-two")
            updated = manager.install_from_staging(second)
            self.assertEqual(updated.version, "2.0.0")
            self.assertIsNotNone(updated.previous_path)

            restored = manager.rollback("zz-Test")
            restored_manifest = json.loads(
                (restored / "language-pack.json").read_text(encoding="utf-8")
            )
            self.assertEqual(restored_manifest["version"], "1.0.0")

    def test_downloader_rejects_non_https(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(LanguagePackError, "HTTPS"):
                VerifiedDownloadManager().download(
                    "http://example.invalid/model.bin",
                    Path(temporary) / "model.bin",
                    expected_sha256="0" * 64,
                    expected_size=1,
                )

    def test_downloader_retries_from_zero_after_integrity_failure(self) -> None:
        class Response:
            status = 200

            def __init__(self, payload: bytes) -> None:
                self.payload = payload
                self.offset = 0
                self.headers = {"Content-Length": str(len(payload))}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def geturl(self) -> str:
                return "https://models.example.test/model.bin"

            def read(self, size: int) -> bytes:
                chunk = self.payload[self.offset : self.offset + size]
                self.offset += len(chunk)
                return chunk

        requests = []
        responses = iter((Response(b"evil"), Response(b"good")))

        def open_response(request, timeout):
            requests.append(request)
            return next(responses)

        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "model.bin"
            with patch("ai_worker.language_packs.urllib.request.urlopen", open_response):
                result = VerifiedDownloadManager(retries=2).download(
                    "https://models.example.test/model.bin",
                    destination,
                    expected_sha256=hashlib.sha256(b"good").hexdigest(),
                    expected_size=4,
                )
            self.assertEqual(result.read_bytes(), b"good")
            self.assertEqual(len(requests), 2)
            self.assertFalse(any(request.has_header("Range") for request in requests))


if __name__ == "__main__":
    unittest.main()
