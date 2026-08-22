#!/usr/bin/env python3
"""Collect license texts for exactly the runtime components in a staged payload."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path


LICENSE_NAMES = ("license", "copying", "notice", "authors", "unlicense")


def is_notice(path: Path) -> bool:
    return path.is_file() and path.name.lower().startswith(LICENSE_NAMES)


def copy_notices(source: Path, destination: Path) -> int:
    copied = 0
    if not source.exists():
        return copied
    for candidate in source.rglob("*"):
        if not is_notice(candidate):
            continue
        relative = candidate.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate, target)
        copied += 1
    return copied


def runtime_rust_packages(workspace: Path) -> list[dict]:
    command = [
        "cargo",
        "metadata",
        "--format-version",
        "1",
        "--filter-platform",
        "x86_64-pc-windows-msvc",
    ]
    metadata = json.loads(subprocess.check_output(command, cwd=workspace, text=True))
    packages = {package["id"]: package for package in metadata["packages"]}
    nodes = {node["id"]: node for node in metadata["resolve"]["nodes"]}
    root = metadata["resolve"]["root"]
    reachable: set[str] = set()
    pending = [root]
    while pending:
        package_id = pending.pop()
        if package_id in reachable:
            continue
        reachable.add(package_id)
        for dependency in nodes[package_id].get("deps", []):
            if any(kind.get("kind") is None for kind in dependency.get("dep_kinds", [])):
                pending.append(dependency["pkg"])
    return [packages[package_id] for package_id in sorted(reachable) if package_id != root]


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", type=Path, default=Path("dist/payload"))
    args = parser.parse_args()
    workspace = Path(__file__).resolve().parents[1]
    payload = (workspace / args.payload).resolve() if not args.payload.is_absolute() else args.payload
    expected_parent = (workspace / "dist").resolve()
    if expected_parent not in payload.parents:
        raise RuntimeError(f"refusing unexpected payload path: {payload}")

    destination = payload / "licenses"
    destination.mkdir(parents=True, exist_ok=True)
    static_licenses = workspace / "licenses"
    if static_licenses.is_dir():
        shutil.copytree(static_licenses, destination / "reviewed", dirs_exist_ok=True)

    site = payload / "python" / "Lib" / "site-packages"
    python_count = 0
    for dist_info in sorted(site.glob("*.dist-info")):
        package_destination = destination / "python-packages" / dist_info.name
        python_count += copy_notices(dist_info, package_destination)
    for package_name in ("onnxruntime", "numpy"):
        python_count += copy_notices(
            site / package_name,
            destination / "python-packages" / package_name,
        )

    rust_count = 0
    for package in runtime_rust_packages(workspace):
        package_root = Path(package["manifest_path"]).parent
        package_destination = (
            destination / "rust-crates" / f"{package['name']}-{package['version']}"
        )
        rust_count += copy_notices(package_root, package_destination)

    shutil.copy2(workspace / "THIRD_PARTY_NOTICES.md", destination / "THIRD_PARTY_NOTICES.md")
    manifest_lines = []
    for notice in sorted(path for path in destination.rglob("*") if path.is_file()):
        relative = notice.relative_to(destination).as_posix()
        manifest_lines.append(f"{digest_file(notice)}  {relative}")
    (destination / "LICENSES-MANIFEST.sha256").write_text(
        "\n".join(manifest_lines) + "\n", encoding="utf-8"
    )
    print(f"collected {python_count} Python and {rust_count} Rust notice files")
    print(f"license bundle: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
