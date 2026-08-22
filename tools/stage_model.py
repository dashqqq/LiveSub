#!/usr/bin/env python3
"""Stage one curated model revision without executing repository code.

The downloader accepts only registry-approved evaluation candidates, rejects
executable model-repository files, pins a full commit, measures disk space, and
writes local SHA-256 provenance for every staged artifact. The development
registry is unsigned, so using it requires an explicit command-line switch.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from ai_worker.language_packs import RegistryError, load_registry, sha256_file


ALLOWED_PATTERNS = (
    "*.json",
    "*.safetensors",
    "*.bin",
    "*.model",
    "*.spm",
    "*.txt",
    "LICENSE*",
    "README.md",
)
DENIED_SUFFIXES = {
    ".py",
    ".pyc",
    ".pyd",
    ".exe",
    ".dll",
    ".bat",
    ".cmd",
    ".ps1",
    ".sh",
    ".so",
    ".dylib",
    ".jar",
    ".ckpt",
    ".pt",
    ".pth",
}


def _trusted_keys(path: Path) -> dict[str, str]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1 or not isinstance(document.get("keys"), dict):
        raise RegistryError("unsupported trusted-key document")
    return {str(key): str(value) for key, value in document["keys"].items()}


def select_model(registry: dict[str, Any], model_id: str) -> dict[str, Any]:
    matches = [item for item in registry.get("models", []) if item.get("id") == model_id]
    if len(matches) != 1:
        raise RegistryError(f"unknown or duplicate curated model ID: {model_id}")
    model = matches[0]
    if model.get("status") not in {"approved_candidate", "approved_reference"}:
        raise RegistryError(
            f"model {model_id} is not eligible for staging: {model.get('status')}"
        )
    if model.get("trust_remote_code"):
        raise RegistryError(f"model {model_id} requires prohibited remote code")
    return model


def _allowed_file(path: str) -> bool:
    value = PurePosixPath(path)
    if value.is_absolute() or ".." in value.parts:
        return False
    if value.suffix.casefold() in DENIED_SUFFIXES:
        return False
    name = value.name.casefold()
    return (
        name == "readme.md"
        or name.startswith("license")
        or value.suffix.casefold()
        in {".json", ".safetensors", ".bin", ".model", ".spm", ".txt"}
    )


def inspect_remote_files(model: dict[str, Any]) -> tuple[list[str], int]:
    from huggingface_hub import HfApi

    api = HfApi()
    info = api.model_info(
        repo_id=model["repository"],
        revision=model["revision"],
        files_metadata=True,
    )
    if info.sha != model["revision"]:
        raise RegistryError(
            f"resolved commit differs from registry: {info.sha} != {model['revision']}"
        )
    files: list[str] = []
    total_bytes = 0
    for sibling in info.siblings or []:
        filename = str(sibling.rfilename)
        if _allowed_file(filename):
            files.append(filename)
            total_bytes += int(sibling.size or 0)
    if not files:
        raise RegistryError("curated repository has no permitted runtime files")
    return sorted(files), total_bytes


def verify_staged_tree(root: Path, expected_files: Iterable[str]) -> list[dict[str, Any]]:
    expected = set(expected_files)
    present: set[str] = set()
    artifacts: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative.startswith(".cache/") or relative == ".livesub-provenance.json":
            continue
        if not _allowed_file(relative):
            raise RegistryError(f"staged repository contains prohibited file: {relative}")
        present.add(relative)
        artifacts.append(
            {
                "path": relative,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    missing = expected - present
    if missing:
        raise RegistryError(f"staged repository is incomplete: {', '.join(sorted(missing))}")
    if not artifacts:
        raise RegistryError("staged repository contains no verified artifacts")
    return artifacts


def verify_registry_artifacts(
    model: dict[str, Any], artifacts: list[dict[str, Any]]
) -> None:
    expected = {
        str(item["path"]): (int(item["size_bytes"]), str(item["sha256"]).casefold())
        for item in model.get("artifacts", [])
    }
    if not expected:
        return
    actual = {
        str(item["path"]): (int(item["size_bytes"]), str(item["sha256"]).casefold())
        for item in artifacts
    }
    if set(actual) != set(expected):
        missing = sorted(set(expected) - set(actual))
        unexpected = sorted(set(actual) - set(expected))
        raise RegistryError(
            "registry artifact set mismatch; "
            f"missing={missing or 'none'}, unexpected={unexpected or 'none'}"
        )
    mismatches = [path for path in expected if actual[path] != expected[path]]
    if mismatches:
        raise RegistryError(
            f"registry artifact size/hash mismatch: {', '.join(sorted(mismatches))}"
        )


def existing_stage_is_valid(destination: Path, model: dict[str, Any]) -> bool:
    provenance_path = destination / ".livesub-provenance.json"
    if not provenance_path.is_file():
        return False
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    if (
        provenance.get("repository") != model["repository"]
        or provenance.get("revision") != model["revision"]
    ):
        return False
    expected = {item["path"]: item for item in provenance.get("artifacts", [])}
    if not expected:
        return False
    for relative, artifact in expected.items():
        path = destination / Path(*PurePosixPath(relative).parts)
        if (
            not path.is_file()
            or path.stat().st_size != artifact.get("size_bytes")
            or sha256_file(path) != artifact.get("sha256")
        ):
            return False
    try:
        verify_registry_artifacts(model, list(expected.values()))
    except RegistryError:
        return False
    return True


def stage_model(model: dict[str, Any], staging_root: Path) -> Path:
    destination = (staging_root / model["id"] / model["revision"]).resolve()
    staging_root = staging_root.resolve()
    if not destination.is_relative_to(staging_root):
        raise RegistryError("model destination escapes staging root")
    if destination.exists():
        if existing_stage_is_valid(destination, model):
            return destination
        raise RegistryError(f"existing model stage is incomplete or corrupted: {destination}")

    files, download_bytes = inspect_remote_files(model)
    free_bytes = shutil.disk_usage(staging_root.parent).free
    required_bytes = download_bytes + max(64 * 1024 * 1024, download_bytes // 20)
    if free_bytes < required_bytes:
        raise RegistryError(
            f"insufficient disk space: required {required_bytes}, available {free_bytes}"
        )
    temporary = destination.with_name(f"{destination.name}.partial-{os.getpid()}")
    temporary.parent.mkdir(parents=True, exist_ok=True)
    if temporary.exists():
        raise RegistryError(f"staging transaction already exists: {temporary}")
    temporary.mkdir()
    try:
        from huggingface_hub import snapshot_download

        snapshot_download(
            repo_id=model["repository"],
            revision=model["revision"],
            local_dir=temporary,
            allow_patterns=list(ALLOWED_PATTERNS),
        )
        artifacts = verify_staged_tree(temporary, files)
        verify_registry_artifacts(model, artifacts)
        provenance = {
            "schema_version": 1,
            "registry_model_id": model["id"],
            "owner": model["owner"],
            "repository": model["repository"],
            "revision": model["revision"],
            "downloaded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "license": model["license"],
            "trust_remote_code": False,
            "remote_files": files,
            "download_bytes_declared": download_bytes,
            "artifacts": artifacts,
        }
        (temporary / ".livesub-provenance.json").write_text(
            json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temporary, destination)
    except Exception:
        # Retain a partial transaction for resumable investigation; it is never
        # treated as installed or loadable because it has no final destination.
        raise
    return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("model_id")
    parser.add_argument(
        "--registry", type=Path, default=WORKSPACE / "registry" / "language-registry.json"
    )
    parser.add_argument(
        "--trusted-keys", type=Path, default=WORKSPACE / "registry" / "trusted-keys.json"
    )
    parser.add_argument(
        "--staging-root", type=Path, default=WORKSPACE / "models" / "staged"
    )
    parser.add_argument("--allow-development-registry", action="store_true")
    args = parser.parse_args()

    registry = load_registry(
        args.registry,
        _trusted_keys(args.trusted_keys),
        allow_development_unsigned=args.allow_development_registry,
    )
    model = select_model(registry, args.model_id)
    started = time.perf_counter()
    destination = stage_model(model, args.staging_root)
    print(
        json.dumps(
            {
                "status": "staged",
                "model_id": model["id"],
                "repository": model["repository"],
                "revision": model["revision"],
                "path": str(destination),
                "elapsed_seconds": round(time.perf_counter() - started, 2),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
