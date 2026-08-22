#!/usr/bin/env python3
"""Fail-closed security and privacy checks for the staged Windows payload."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path


ALLOWED_EXECUTABLES = {"livesub.exe", "python.exe", "pythonw.exe"}
FORBIDDEN_SUFFIXES = {
    ".bat",
    ".cmd",
    ".dmp",
    ".dump",
    ".flac",
    ".key",
    ".m4a",
    ".mp3",
    ".ogg",
    ".p12",
    ".pfx",
    ".ps1",
    ".trace",
    ".vbs",
    ".wav",
    ".wsf",
}
FORBIDDEN_NAMES = {
    ".env",
    ".git-credentials",
    "credentials.json",
    "id_dsa",
    "id_ed25519",
    "id_rsa",
    "secrets.json",
}
SECRET_PATTERNS = {
    # Anchor PEM headers to a complete line. Some cryptography libraries contain
    # the marker as a quoted source-code constant; that is not key material.
    "private key": re.compile(
        rb"^-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----\r?$", re.MULTILINE
    ),
    "GitHub classic token": re.compile(rb"ghp_[A-Za-z0-9]{30,}"),
    "GitHub fine-grained token": re.compile(rb"github_pat_[A-Za-z0-9_]{30,}"),
    "AWS access key": re.compile(rb"AKIA[0-9A-Z]{16}"),
}
BINARY_SUFFIXES = {".dll", ".exe", ".pyd"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative(path: Path, payload: Path) -> str:
    return path.relative_to(payload).as_posix()


def audit(payload: Path) -> dict[str, object]:
    files = sorted(path for path in payload.rglob("*") if path.is_file())
    findings: list[dict[str, str]] = []
    binaries: list[dict[str, object]] = []

    local_markers = []
    for candidate in (str(Path.cwd().resolve()), os.environ.get("USERPROFILE", "")):
        candidate = candidate.strip()
        if candidate:
            local_markers.append(candidate.encode("utf-8").lower())
            local_markers.append(candidate.replace("\\", "/").encode("utf-8").lower())

    for path in files:
        rel = relative(path, payload)
        lowered_name = path.name.lower()
        lowered_parts = {part.lower() for part in path.parts}
        suffix = path.suffix.lower()

        if lowered_name in FORBIDDEN_NAMES or lowered_name.startswith(".env."):
            findings.append({"path": rel, "reason": "sensitive filename"})
        if suffix in FORBIDDEN_SUFFIXES:
            findings.append({"path": rel, "reason": f"forbidden release suffix {suffix}"})
        if "__pycache__" in lowered_parts or suffix in {".pyc", ".pyo"}:
            findings.append({"path": rel, "reason": "Python cache/debug artifact"})
        if "av" in lowered_parts or lowered_name.startswith("av-") or "av.libs" in lowered_parts:
            findings.append({"path": rel, "reason": "PyAV payload must not be bundled"})
        if lowered_name.startswith(("av-", "ffmpeg", "libav", "x264", "x265")):
            findings.append({"path": rel, "reason": "media/codec payload must not be bundled"})
        if suffix == ".exe" and lowered_name not in ALLOWED_EXECUTABLES:
            findings.append({"path": rel, "reason": "unexpected executable"})

        if suffix in BINARY_SUFFIXES:
            binaries.append(
                {
                    "path": rel,
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )

        # Scan bounded files for high-confidence secrets and machine-local paths.
        if path.stat().st_size <= 8 * 1024 * 1024:
            data = path.read_bytes()
            lowered_data = data.lower()
            for label, pattern in SECRET_PATTERNS.items():
                if pattern.search(data):
                    findings.append({"path": rel, "reason": label})
            if any(marker in lowered_data for marker in local_markers):
                findings.append({"path": rel, "reason": "build-machine personal/workspace path"})

    # Report every occurrence once even if more than one check found the same issue.
    unique = {(item["path"], item["reason"]): item for item in findings}
    findings = [unique[key] for key in sorted(unique)]
    return {
        "schema": "LiveSub release payload audit/v1",
        "generatedUtc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "payload": str(payload),
        "fileCount": len(files),
        "payloadBytes": sum(path.stat().st_size for path in files),
        "binaryCount": len(binaries),
        "binaries": binaries,
        "findings": findings,
        "result": "PASS" if not findings else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", type=Path, default=Path("dist/payload"))
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("release/payload-audit-v0.1.0-preview.json"),
    )
    args = parser.parse_args()
    workspace = Path(__file__).resolve().parents[1]
    payload = (workspace / args.payload).resolve() if not args.payload.is_absolute() else args.payload.resolve()
    report = (workspace / args.report).resolve() if not args.report.is_absolute() else args.report.resolve()
    if not payload.is_dir():
        raise SystemExit(f"payload directory does not exist: {payload}")
    result = audit(payload)
    try:
        result["payload"] = payload.relative_to(workspace).as_posix()
    except ValueError:
        result["payload"] = payload.name
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {report}")
    print(f"payload audit: {result['result']} ({len(result['findings'])} findings)")
    if result["findings"]:
        for finding in result["findings"]:
            print(f"- {finding['path']}: {finding['reason']}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
