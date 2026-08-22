"""Verified, rollback-safe local language-pack infrastructure.

This module performs no model discovery and executes no model code. It consumes
only candidates from a curated registry, verifies signatures/hashes, and moves a
fully validated staging directory into the application data directory.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
WINDOWS_REPARSE_POINT = 0x400


class RegistryError(ValueError):
    pass


class LanguagePackError(ValueError):
    pass


def _validate_registry_artifacts(
    model_id: str,
    artifacts: Any,
    *,
    required: bool,
) -> None:
    if not isinstance(artifacts, list) or not artifacts:
        if required:
            raise RegistryError(
                f"production model {model_id} has no registry-pinned artifacts"
            )
        return
    paths: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            raise RegistryError(f"model {model_id} has an invalid artifact entry")
        relative = str(artifact.get("path", ""))
        value = PurePosixPath(relative)
        if value.is_absolute() or ".." in value.parts or not value.parts:
            raise RegistryError(f"model {model_id} has an unsafe artifact path")
        if relative in paths:
            raise RegistryError(f"model {model_id} has duplicate artifact {relative}")
        paths.add(relative)
        digest = str(artifact.get("sha256", "")).casefold()
        if not SHA256_PATTERN.fullmatch(digest):
            raise RegistryError(f"model {model_id} has an invalid artifact SHA-256")
        size = artifact.get("size_bytes")
        if not isinstance(size, int) or size < 1:
            raise RegistryError(f"model {model_id} has an invalid artifact size")


def canonical_json(document: Mapping[str, Any], *, exclude_signature: bool = True) -> bytes:
    value = dict(document)
    if exclude_signature:
        value.pop("signature", None)
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_ed25519(payload: bytes, signature: str, public_key: str) -> None:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as error:
        raise RegistryError("Ed25519 verification runtime is unavailable") from error
    try:
        key_bytes = base64.b64decode(public_key, validate=True)
        signature_bytes = base64.b64decode(signature, validate=True)
        Ed25519PublicKey.from_public_bytes(key_bytes).verify(signature_bytes, payload)
    except Exception as error:
        raise RegistryError("invalid Ed25519 registry/pack signature") from error


def verify_signed_document(
    document: Mapping[str, Any],
    trusted_keys: Mapping[str, str],
    *,
    allow_development_unsigned: bool = False,
) -> bool:
    signature = document.get("signature")
    if not isinstance(signature, Mapping):
        raise RegistryError("signed document has no signature object")
    status = signature.get("status")
    encoded = signature.get("value")
    if status == "development_unsigned" and not encoded:
        if allow_development_unsigned:
            return False
        raise RegistryError("unsigned development registry/pack is disabled")
    if signature.get("algorithm") != "ed25519":
        raise RegistryError("only Ed25519 signatures are accepted")
    key_id = str(signature.get("key_id", ""))
    public_key = trusted_keys.get(key_id)
    if not public_key:
        raise RegistryError(f"untrusted signing key: {key_id}")
    if not isinstance(encoded, str) or not encoded:
        raise RegistryError("signature value is missing")
    _verify_ed25519(canonical_json(document), encoded, public_key)
    return True


def load_registry(
    path: Path,
    trusted_keys: Mapping[str, str],
    *,
    allow_development_unsigned: bool = False,
) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1:
        raise RegistryError("unsupported registry schema")
    verify_signed_document(
        document,
        trusted_keys,
        allow_development_unsigned=allow_development_unsigned,
    )
    identifiers: set[str] = set()
    production_ready = document.get("production_ready") is True
    for model in document.get("models", []):
        model_id = str(model.get("id", ""))
        if not model_id or model_id in identifiers:
            raise RegistryError(f"missing or duplicate model ID: {model_id!r}")
        identifiers.add(model_id)
        revision = str(model.get("revision", ""))
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise RegistryError(f"model {model_id} has an unpinned revision")
        license_info = model.get("license", {})
        status = str(model.get("status", ""))
        if status.startswith("approved"):
            if not license_info.get("commercial_use_allowed"):
                raise RegistryError(f"approved model {model_id} is not commercial-use compatible")
            if not license_info.get("redistribution_allowed"):
                raise RegistryError(f"approved model {model_id} cannot be redistributed")
            if model.get("trust_remote_code"):
                raise RegistryError(f"approved model {model_id} requires remote code")
            _validate_registry_artifacts(
                model_id,
                model.get("artifacts"),
                required=production_ready,
            )
    return document


def _safe_artifact(root: Path, relative: str) -> Path:
    value = PurePosixPath(relative)
    if value.is_absolute() or ".." in value.parts or not value.parts:
        raise LanguagePackError(f"unsafe artifact path: {relative!r}")
    path = (root / Path(*value.parts)).resolve()
    if not path.is_relative_to(root.resolve()):
        raise LanguagePackError(f"artifact escapes language pack: {relative!r}")
    return path


def _is_link_or_reparse(path: Path) -> bool:
    stat = path.lstat()
    attributes = int(getattr(stat, "st_file_attributes", 0))
    return path.is_symlink() or bool(attributes & WINDOWS_REPARSE_POINT)


def _pack_files(pack_root: Path) -> set[str]:
    files: set[str] = set()
    for current, directories, filenames in os.walk(pack_root, followlinks=False):
        current_path = Path(current)
        for name in (*directories, *filenames):
            candidate = current_path / name
            if _is_link_or_reparse(candidate):
                raise LanguagePackError(
                    f"language pack contains a link/reparse point: {candidate.name}"
                )
        for name in filenames:
            relative = (current_path / name).relative_to(pack_root).as_posix()
            key = relative.casefold()
            if key in files:
                raise LanguagePackError(f"duplicate language-pack path: {relative}")
            files.add(key)
    return files


def verify_pack(
    pack_root: Path,
    manifest: Mapping[str, Any],
    trusted_keys: Mapping[str, str],
    *,
    allow_development_unsigned: bool = False,
) -> dict[str, Any]:
    pack_root = pack_root.resolve()
    if not pack_root.is_dir():
        raise LanguagePackError("language-pack root is missing")
    if manifest.get("schema_version") != 1:
        raise LanguagePackError("unsupported language-pack schema")
    try:
        signature_verified = verify_signed_document(
            manifest,
            trusted_keys,
            allow_development_unsigned=allow_development_unsigned,
        )
    except RegistryError as error:
        raise LanguagePackError(str(error)) from error
    if manifest.get("acceptance", {}).get("status") != "passed":
        raise LanguagePackError("language pack has not passed local acceptance")
    pack_license = manifest.get("license", {})
    if not pack_license.get("commercial_use_allowed"):
        raise LanguagePackError("language pack license does not allow commercial use")
    if not pack_license.get("redistribution_allowed"):
        raise LanguagePackError("language pack license does not allow redistribution")
    models = manifest.get("models", [])
    if not isinstance(models, list) or not models:
        raise LanguagePackError("language pack has no model provenance")
    for model in models:
        if not isinstance(model, Mapping):
            raise LanguagePackError("language pack has invalid model provenance")
        repository = str(model.get("repository", ""))
        owner = str(model.get("owner", ""))
        revision = str(model.get("revision", ""))
        downloaded_at = str(model.get("downloaded_at", ""))
        if not repository or "/" not in repository or not owner:
            raise LanguagePackError("language-pack model owner/repository is missing")
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise LanguagePackError(f"model {repository} has an unpinned revision")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", downloaded_at):
            raise LanguagePackError(f"model {repository} has no normalized download date")
        if model.get("trust_remote_code"):
            raise LanguagePackError(f"model {repository} requires unreviewed remote code")
        model_license = model.get("license", {})
        if not model_license.get("commercial_use_allowed"):
            raise LanguagePackError(f"model {repository} is not commercial-use compatible")
        if not model_license.get("redistribution_allowed"):
            raise LanguagePackError(f"model {repository} cannot be redistributed")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise LanguagePackError("language pack contains no verified artifacts")
    expected_files = {"language-pack.json"}
    total_bytes = 0
    checked_files = 0
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            raise LanguagePackError("language pack has an invalid artifact entry")
        relative = str(artifact.get("path", ""))
        relative_key = PurePosixPath(relative).as_posix().casefold()
        if relative_key in expected_files:
            raise LanguagePackError(f"duplicate language-pack artifact: {relative}")
        expected_files.add(relative_key)
        expected_hash = str(artifact.get("sha256", "")).casefold()
        if not SHA256_PATTERN.fullmatch(expected_hash):
            raise LanguagePackError(f"invalid SHA-256 for {artifact.get('path')}")
        path = _safe_artifact(pack_root, relative)
        if not path.is_file():
            raise LanguagePackError(f"language-pack artifact is missing: {path}")
        expected_size = artifact.get("size_bytes")
        if isinstance(expected_size, bool) or not isinstance(expected_size, int):
            raise LanguagePackError(f"invalid size for {path.name}")
        if expected_size < 1:
            raise LanguagePackError(f"invalid size for {path.name}")
        actual_size = path.stat().st_size
        if actual_size != expected_size:
            raise LanguagePackError(
                f"size mismatch for {path.name}: expected {expected_size}, got {actual_size}"
            )
        actual_hash = sha256_file(path)
        if actual_hash != expected_hash:
            raise LanguagePackError(f"SHA-256 mismatch for {path.name}")
        total_bytes += actual_size
        checked_files += 1
    actual_files = _pack_files(pack_root)
    unverified_files = sorted(actual_files - expected_files)
    missing_files = sorted(expected_files - actual_files)
    if unverified_files:
        raise LanguagePackError(
            f"language pack contains unverified files: {', '.join(unverified_files)}"
        )
    if missing_files:
        raise LanguagePackError(
            f"language pack is missing declared files: {', '.join(missing_files)}"
        )
    return {
        "files": checked_files,
        "bytes": total_bytes,
        "signature_verified": signature_verified,
    }


@dataclass(frozen=True)
class InstallResult:
    language: str
    version: str
    installed_path: Path
    previous_path: Path | None
    verified_files: int
    verified_bytes: int


class LanguagePackManager:
    def __init__(
        self,
        app_data: Path,
        *,
        trusted_keys: Mapping[str, str],
        allow_development_unsigned: bool = False,
    ) -> None:
        self.app_data = app_data.resolve()
        self.languages_root = self.app_data / "languages"
        self.staging_root = self.app_data / "staging"
        self.backup_root = self.app_data / "pack-backups"
        self.failed_root = self.app_data / "failed-packs"
        self.trusted_keys = dict(trusted_keys)
        self.allow_development_unsigned = allow_development_unsigned
        for path in (
            self.languages_root,
            self.staging_root,
            self.backup_root,
            self.failed_root,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def _active_document(self) -> dict[str, Any]:
        path = self.languages_root / "active.json"
        if not path.is_file():
            return {"schema_version": 1, "languages": {}}
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_active(self, document: Mapping[str, Any]) -> None:
        destination = self.languages_root / "active.json"
        temporary = self.languages_root / "active.json.new"
        temporary.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, destination)

    def install_from_staging(self, staging: Path) -> InstallResult:
        staging = staging.resolve()
        if not staging.is_relative_to(self.staging_root):
            raise LanguagePackError("staged pack is outside the managed staging directory")
        manifest_path = staging / "language-pack.json"
        if not manifest_path.is_file():
            raise LanguagePackError("staged pack has no language-pack.json")
        if _is_link_or_reparse(manifest_path):
            raise LanguagePackError("language-pack manifest cannot be a link/reparse point")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        verification = verify_pack(
            staging,
            manifest,
            self.trusted_keys,
            allow_development_unsigned=self.allow_development_unsigned,
        )
        language = str(manifest.get("language", ""))
        version = str(manifest.get("version", ""))
        if not re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]+)?", language):
            raise LanguagePackError(f"invalid language code: {language!r}")
        if not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z._-]*", version):
            raise LanguagePackError(f"invalid language-pack version: {version!r}")
        free_bytes = shutil.disk_usage(self.app_data).free
        required_bytes = verification["bytes"] + max(64 * 1024 * 1024, verification["bytes"] // 20)
        if free_bytes < required_bytes:
            raise LanguagePackError(
                f"insufficient disk space: required {required_bytes}, available {free_bytes}"
            )
        destination = self.languages_root / language
        previous: Path | None = None
        if destination.exists():
            previous = self.backup_root / f"{language}-{int(time.time() * 1000)}"
            os.replace(destination, previous)
        try:
            os.replace(staging, destination)
            active = self._active_document()
            active.setdefault("languages", {})[language] = {
                "version": version,
                "path": str(destination),
                "activated_at_unix_ms": int(time.time() * 1000),
                "previous_path": str(previous) if previous else None,
            }
            self._write_active(active)
        except Exception:
            if destination.exists():
                failed = self.failed_root / f"{language}-{int(time.time() * 1000)}"
                os.replace(destination, failed)
            if previous is not None and previous.exists():
                os.replace(previous, destination)
            raise
        return InstallResult(
            language=language,
            version=version,
            installed_path=destination,
            previous_path=previous,
            verified_files=verification["files"],
            verified_bytes=verification["bytes"],
        )

    def rollback(self, language: str) -> Path:
        active = self._active_document()
        entry = active.get("languages", {}).get(language)
        if not entry or not entry.get("previous_path"):
            raise LanguagePackError(f"no previous known-good pack for {language}")
        previous = Path(entry["previous_path"]).resolve()
        if not previous.is_relative_to(self.backup_root) or not previous.is_dir():
            raise LanguagePackError("recorded rollback pack is missing or unsafe")
        previous_manifest_path = previous / "language-pack.json"
        if not previous_manifest_path.is_file() or _is_link_or_reparse(
            previous_manifest_path
        ):
            raise LanguagePackError("rollback language-pack manifest is missing or unsafe")
        previous_manifest = json.loads(previous_manifest_path.read_text(encoding="utf-8"))
        if str(previous_manifest.get("language", "")) != language:
            raise LanguagePackError("rollback pack language does not match the active language")
        verify_pack(
            previous,
            previous_manifest,
            self.trusted_keys,
            allow_development_unsigned=self.allow_development_unsigned,
        )
        current = self.languages_root / language
        failed = self.failed_root / f"{language}-{int(time.time() * 1000)}"
        moved_current = False
        try:
            if current.exists():
                os.replace(current, failed)
                moved_current = True
            os.replace(previous, current)
            restored_manifest = previous_manifest
            entry.update(
                {
                    "version": str(restored_manifest["version"]),
                    "path": str(current),
                    "previous_path": None,
                    "activated_at_unix_ms": int(time.time() * 1000),
                }
            )
            self._write_active(active)
        except Exception:
            if current.exists() and not previous.exists():
                os.replace(current, previous)
            if moved_current and failed.exists() and not current.exists():
                os.replace(failed, current)
            raise
        return current


ProgressCallback = Callable[[int, int | None], None]


class VerifiedDownloadManager:
    """HTTPS-only resumable downloader with fail-closed checksum handling."""

    def __init__(self, retries: int = 3, timeout_seconds: int = 30) -> None:
        self.retries = max(1, retries)
        self.timeout_seconds = max(5, timeout_seconds)

    def download(
        self,
        url: str,
        destination: Path,
        *,
        expected_sha256: str,
        expected_size: int | None,
        progress: ProgressCallback | None = None,
    ) -> Path:
        if not url.startswith("https://"):
            raise LanguagePackError("model downloads require HTTPS")
        if not SHA256_PATTERN.fullmatch(expected_sha256.casefold()):
            raise LanguagePackError("download has no valid expected SHA-256")
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(destination.name + ".part")
        if expected_size is not None:
            if isinstance(expected_size, bool) or not isinstance(expected_size, int):
                raise LanguagePackError("download has an invalid expected size")
            if expected_size < 1:
                raise LanguagePackError("download has an invalid expected size")
            existing_bytes = partial.stat().st_size if partial.is_file() else 0
            remaining_bytes = max(0, expected_size - existing_bytes)
            reserve = max(64 * 1024 * 1024, expected_size // 20)
            available_bytes = shutil.disk_usage(destination.parent).free
            if available_bytes < remaining_bytes + reserve:
                raise LanguagePackError(
                    "insufficient disk space for model download: "
                    f"required {remaining_bytes + reserve}, available {available_bytes}"
                )
        last_error: Exception | None = None
        for _ in range(self.retries):
            try:
                offset = partial.stat().st_size if partial.is_file() else 0
                request = urllib.request.Request(url)
                if offset:
                    request.add_header("Range", f"bytes={offset}-")
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    response_url = str(response.geturl())
                    if not response_url.startswith("https://"):
                        raise LanguagePackError("model download redirected away from HTTPS")
                    resumed = offset > 0 and getattr(response, "status", None) == 206
                    mode = "ab" if resumed else "wb"
                    if not resumed:
                        offset = 0
                    content_length = response.headers.get("Content-Length")
                    total = (
                        offset + int(content_length)
                        if content_length is not None
                        else expected_size
                    )
                    with partial.open(mode) as handle:
                        downloaded = offset
                        while chunk := response.read(1024 * 1024):
                            handle.write(chunk)
                            downloaded += len(chunk)
                            if progress:
                                progress(downloaded, total)
                actual_size = partial.stat().st_size
                if expected_size is not None and actual_size != expected_size:
                    raise LanguagePackError(
                        f"download size mismatch: expected {expected_size}, got {actual_size}"
                    )
                if sha256_file(partial) != expected_sha256.casefold():
                    raise LanguagePackError("download SHA-256 mismatch")
                os.replace(partial, destination)
                return destination
            except (OSError, urllib.error.URLError, LanguagePackError) as error:
                last_error = error
                if isinstance(error, LanguagePackError) and partial.exists():
                    partial.unlink()
        if partial.exists():
            partial.unlink()
        raise LanguagePackError(f"download failed after {self.retries} attempts: {last_error}")
