#!/usr/bin/env python3
"""Generate payload-derived CycloneDX and human-readable LiveSub SBOMs."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import uuid
from email.parser import Parser
from pathlib import Path
from typing import Any


MODEL_REVISION = "536b0662742c02347bc0e980a01041f333bce120"
MODEL_REPOSITORY = "https://huggingface.co/Systran/faster-whisper-small"
MODEL_FILES = {
    "config.json": "b55496ac7940a7ae47d2c01eab40edfd8701feec1229d9cce3b40014383fb828",
    "model.bin": "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671",
    "tokenizer.json": "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab",
    "vocabulary.txt": "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def properties(**values: str) -> list[dict[str, str]]:
    return [{"name": f"livesub:{key}", "value": value} for key, value in values.items()]


def component(
    kind: str,
    name: str,
    version: str,
    license_name: str,
    *,
    ref: str,
    upstream: str = "",
    purl: str = "",
    hashes: list[dict[str, str]] | None = None,
    bundled: str = "YES",
    runtime: str = "YES",
    evidence: str = "",
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": kind,
        "bom-ref": ref,
        "name": name,
        "version": version,
        "licenses": [{"license": {"name": license_name}}],
        "properties": properties(Bundled=bundled, RuntimeDependency=runtime, Evidence=evidence),
    }
    if purl:
        result["purl"] = purl
    if upstream:
        result["externalReferences"] = [{"type": "website", "url": upstream}]
    if hashes:
        result["hashes"] = hashes
    return result


def metadata_values(text: str) -> tuple[str, str, str, str]:
    metadata = Parser().parsestr(text)
    name = metadata.get("Name", "UNKNOWN")
    version = metadata.get("Version", "UNKNOWN")
    license_name = metadata.get("License-Expression") or metadata.get("License") or "UNKNOWN"
    if license_name == "UNKNOWN":
        for classifier in metadata.get_all("Classifier", []):
            if classifier.startswith("License ::"):
                license_name = classifier.rsplit("::", 1)[-1].strip()
                break
    upstream = metadata.get("Home-page", "")
    for project_url in metadata.get_all("Project-URL", []):
        label, _, url = project_url.partition(",")
        if label.strip().lower() in {"source", "repository", "homepage"}:
            upstream = url.strip()
            break
    return name, version, license_name, upstream


def python_components(payload: Path) -> list[dict[str, Any]]:
    site = payload / "python" / "Lib" / "site-packages"
    found = []
    for dist_info in sorted(site.glob("*.dist-info"), key=lambda path: path.name.lower()):
        metadata_path = dist_info / "METADATA"
        if not metadata_path.is_file():
            continue
        name, version, license_name, upstream = metadata_values(
            metadata_path.read_text(encoding="utf-8", errors="replace")
        )
        normalized = name.lower().replace("_", "-")
        found.append(
            component(
                "library",
                name,
                version,
                license_name,
                ref=f"pkg:pypi/{normalized}@{version}",
                upstream=upstream,
                purl=f"pkg:pypi/{normalized}@{version}",
                evidence=f"{dist_info.name}/METADATA in release payload",
            )
        )
    return found


def rust_components(workspace: Path) -> list[dict[str, Any]]:
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

    found = []
    for package_id in sorted(reachable):
        if package_id == root:
            continue
        package = packages[package_id]
        name = package["name"]
        version = package["version"]
        found.append(
            component(
                "library",
                name,
                version,
                package.get("license") or "UNKNOWN",
                ref=f"pkg:cargo/{name}@{version}",
                upstream=package.get("repository") or package.get("homepage") or "",
                purl=f"pkg:cargo/{name}@{version}",
                evidence="Cargo.lock and Windows-filtered normal dependency graph",
            )
        )
    return found


def file_hash(path: Path) -> list[dict[str, str]]:
    return [{"alg": "SHA-256", "content": sha256(path)}]


def assert_model(payload: Path) -> Path:
    snapshot = (
        payload
        / "models"
        / "models--Systran--faster-whisper-small"
        / "snapshots"
        / MODEL_REVISION
    )
    for filename, expected in MODEL_FILES.items():
        actual = sha256(snapshot / filename)
        if actual != expected:
            raise RuntimeError(f"model hash mismatch for {filename}: {actual}")
    return snapshot


def manual_components(payload: Path, installer: Path) -> list[dict[str, Any]]:
    snapshot = assert_model(payload)
    vad = payload / "python" / "Lib" / "site-packages" / "faster_whisper" / "assets" / "silero_vad_v6.onnx"
    ctranslate = payload / "python" / "Lib" / "site-packages" / "ctranslate2"
    root_license = payload / "LICENSE"
    livesub_license = "MIT" if root_license.is_file() else "OWNER REVIEW REQUIRED: Cargo.toml says MIT; root LICENSE missing"
    livesub_evidence = "release payload/livesub.exe and root LICENSE" if root_license.is_file() else "release payload/livesub.exe; repository root LICENSE is absent"
    result = [
        component(
            "application",
            "LiveSub",
            "0.1.0-preview",
            livesub_license,
            ref="pkg:generic/livesub@0.1.0-preview",
            upstream="https://github.com/dashqqq/LiveSub",
            purl="pkg:generic/livesub@0.1.0-preview",
            hashes=file_hash(payload / "livesub.exe"),
            evidence=livesub_evidence,
        ),
        component(
            "application",
            "LiveSub Setup",
            "0.1.0-preview",
            "Inno Setup License",
            ref="pkg:generic/livesub-setup@0.1.0-preview",
            hashes=file_hash(installer),
            evidence="dist/LiveSub-Setup.exe built with Inno Setup 6.7.3",
        ),
        component(
            "framework",
            "CPython embeddable runtime",
            "3.12.10",
            "Python-2.0",
            ref="pkg:generic/cpython@3.12.10?distribution=embeddable-windows-x64",
            upstream="https://www.python.org/downloads/release/python-31210/",
            hashes=file_hash(payload / "python" / "python312.dll"),
            evidence="python312.dll and python/LICENSE.txt in release payload",
        ),
        component(
            "machine-learning-model",
            "SYSTRAN faster-whisper-small",
            MODEL_REVISION,
            "MIT",
            ref=f"pkg:huggingface/Systran/faster-whisper-small@{MODEL_REVISION}",
            upstream=MODEL_REPOSITORY,
            purl=f"pkg:huggingface/Systran/faster-whisper-small@{MODEL_REVISION}",
            hashes=file_hash(snapshot / "model.bin"),
            evidence="Pinned Hugging Face revision; conversion of openai/whisper-small",
        ),
        component(
            "machine-learning-model",
            "Silero VAD v6 graph supplied by faster-whisper",
            "v6/faster-whisper-1.2.1",
            "MIT",
            ref="pkg:generic/silero-vad@v6?distribution=faster-whisper-1.2.1",
            upstream="https://github.com/SYSTRAN/faster-whisper/tree/v1.2.1",
            hashes=file_hash(vad),
            evidence="faster_whisper/assets/silero_vad_v6.onnx in release payload",
        ),
    ]
    native = [
        ("Microsoft Visual C++ Runtime", "14.42.34438.0", "Microsoft Visual C++ Runtime terms", "https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files", payload / "python" / "vcruntime140.dll", "Microsoft Distributable Code in CPython 3.12.10 Windows build"),
        ("Intel OpenMP Runtime", "20250910", "Intel Simplified Software License", "https://www.intel.com/content/www/us/en/content-details/749362/intel-simplified-software-license-version-october-2022.html", ctranslate / "libiomp5md.dll", "CTranslate2 4.8.1 Windows wheel; Authenticode signer Intel Corporation"),
        ("Intel oneMKL", "2025.3.0.372", "Intel Simplified Software License", "https://www.intel.com/content/www/us/en/developer/articles/tool/onemkl-license-faq.html", ctranslate / "ctranslate2.dll", "Statically incorporated; pinned by CTranslate2 v4.8.1 Windows wheel build script"),
        ("NVIDIA cuDNN compatibility runtime", "9.10.2.21", "NVIDIA SDK License Agreement and cuDNN Supplement", "https://docs.nvidia.com/deeplearning/cudnn/backend/reference/eula.html", ctranslate / "cudnn64_9.dll", "CTranslate2 4.8.1 wheel compatibility DLL; Authenticode signer NVIDIA Corporation"),
    ]
    for name, version, license_name, upstream, path, evidence in native:
        result.append(
            component(
                "library",
                name,
                version,
                license_name,
                ref=f"pkg:generic/{name.lower().replace(' ', '-')}@{version}",
                upstream=upstream,
                hashes=file_hash(path),
                evidence=evidence,
            )
        )

    ctranslate_third_party = [
        ("BS thread pool", "5.1.0", "MIT", "https://github.com/bshoshany/thread-pool"),
        ("oneDNN", "3.1.1", "Apache-2.0", "https://github.com/oneapi-src/oneDNN"),
        ("cpu_features", "8a494eb1e158ec2050e5f699a504fbc9b896a43b", "Apache-2.0", "https://github.com/google/cpu_features"),
        ("CUTLASS", "bbe579a9e3beb6ea6626d9227ec32d0dae119a49", "BSD-3-Clause", "https://github.com/NVIDIA/cutlass"),
        ("cxxopts", "c74846a891b3cc3bfa992d588b1295f528d43039", "MIT", "https://github.com/jarro2783/cxxopts"),
        ("ruy", "363f252289fb7a1fba1703d99196524698cb884d", "Apache-2.0", "https://github.com/google/ruy"),
        ("spdlog", "76fb40d95455f249bd70824ecfcae7a8f0930fa3", "MIT", "https://github.com/gabime/spdlog"),
        ("Thrust", "b5fe509fd11a925f90d6495176707cc1184eed9d", "Apache-2.0", "https://github.com/NVIDIA/thrust"),
        ("Julien Pommier SIMD math functions", "CTranslate2-v4.8.1", "Zlib", "https://github.com/OpenNMT/CTranslate2/tree/v4.8.1/third_party"),
    ]
    for name, version, license_name, upstream in ctranslate_third_party:
        result.append(
            component(
                "library",
                name,
                version,
                license_name,
                ref=f"pkg:generic/ctranslate2-third-party/{name.lower().replace(' ', '-')}@{version}",
                upstream=upstream,
                evidence="Pinned CTranslate2 v4.8.1 source/submodule; statically incorporated where selected by Windows wheel build",
            )
        )
    return result


def build_sbom(workspace: Path, payload: Path, installer: Path) -> dict[str, Any]:
    build_info = (payload / "BUILD-INFO.txt").read_text(encoding="utf-8")
    commit = next(
        (line.partition(":")[2].strip() for line in build_info.splitlines() if line.startswith("Build commit:")),
        "unrecorded",
    )
    timestamp = next(
        (line.partition(":")[2].strip() for line in build_info.splitlines() if line.startswith("Build timestamp (UTC):")),
        "unrecorded",
    )
    components = manual_components(payload, installer)
    components.extend(python_components(payload))
    components.extend(rust_components(workspace))
    components.sort(key=lambda item: item["bom-ref"])
    serial_seed = f"{commit}:{sha256(installer)}"
    return {
        "$schema": "https://cyclonedx.org/schema/bom-1.6.schema.json",
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, serial_seed)}",
        "version": 1,
        "metadata": {
            "timestamp": timestamp,
            "tools": {"components": [{"type": "application", "name": "LiveSub payload SBOM generator", "version": "1"}]},
            "component": {"type": "application", "bom-ref": "pkg:generic/livesub@0.1.0-preview", "name": "LiveSub", "version": "0.1.0-preview"},
            "properties": properties(BuildCommit=commit, InstallerSHA256=sha256(installer)),
        },
        "components": components,
    }


def property_map(item: dict[str, Any]) -> dict[str, str]:
    return {entry["name"].removeprefix("livesub:"): entry["value"] for entry in item.get("properties", [])}


def decision_for(license_name: str) -> str:
    normalized = license_name.upper()
    if "OWNER REVIEW REQUIRED" in normalized:
        return "OWNER REVIEW REQUIRED"
    if "UNKNOWN" in normalized:
        return "UNKNOWN"
    return "CLEARED WITH NOTICE"


def render_markdown(sbom: dict[str, Any], payload: Path, installer: Path) -> str:
    files = [path for path in payload.rglob("*") if path.is_file()]
    total_bytes = sum(path.stat().st_size for path in files)
    metadata_props = property_map(sbom["metadata"])
    lines = [
        "# LiveSub v0.1.0 Preview software bill of materials",
        "",
        f"- Build commit: `{metadata_props['BuildCommit']}`",
        f"- Installer: `dist/{installer.name}`",
        f"- Installer SHA-256: `{metadata_props['InstallerSHA256']}`",
        f"- Payload files: {len(files):,}",
        f"- Payload bytes: {total_bytes:,}",
        f"- Components recorded: {len(sbom['components']):,}",
        "",
        "This inventory is derived from the staged release payload, installed Python metadata, the Windows-filtered normal Cargo dependency graph, and separately identified native/model components. Build-only and development-only dependencies are excluded unless their code is present in the generated installer. It is an engineering compliance record, not legal advice.",
        "",
        "## Model artifacts",
        "",
        f"- `Systran/faster-whisper-small` revision `{MODEL_REVISION}`; CTranslate2 conversion of `openai/whisper-small`; MIT redistribution basis recorded from both upstream projects.",
    ]
    for filename, digest in MODEL_FILES.items():
        lines.append(f"  - `{filename}`: `{digest}`")
    root_license_conclusion = (
        "- The canonical root LiveSub `LICENSE` is included in the payload and recorded as a distinct application-source grant."
        if (payload / "LICENSE").is_file()
        else "- `Cargo.toml` declares MIT, but the root LiveSub copyright holder has not been established and a root `LICENSE` remains absent. This is intentionally not converted to `CLEARED` by this generator."
    )
    lines.extend(
        [
            "- `silero_vad_v6.onnx`: `4cbf549b8326f60f80f2536d9eefeb450a9abe83365a098031c89719f1be17d2`; shipped by faster-whisper 1.2.1 under the faster-whisper/Silero MIT notices.",
            "- Qwen, IndicTrans2, OPUS/Marian, M2M100, NLLB, and other registry candidates are metadata only and are **not bundled**.",
            "",
            "## Component inventory",
            "",
            "| Component | Version | Bundled | Runtime | License | Redistribution/commercial use | Attribution/license inclusion | Source obligation | Evidence | Decision |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in sbom["components"]:
        props = property_map(item)
        license_name = item["licenses"][0]["license"]["name"]
        decision = decision_for(license_name)
        rights = "Permitted under recorded terms" if decision != "UNKNOWN" else "Not established"
        if decision == "OWNER REVIEW REQUIRED":
            rights = "Owner must confirm copyright holder and source-license grant"
        source_obligation = "Preserve component license/notices; no LiveSub source disclosure identified"
        row = [
            item["name"],
            item["version"],
            props.get("Bundled", "YES"),
            props.get("RuntimeDependency", "YES"),
            license_name,
            rights,
            "Include applicable notice/license text",
            source_obligation,
            props.get("Evidence", ""),
            decision,
        ]
        lines.append("| " + " | ".join(value.replace("|", "\\|").replace("\n", " ") for value in row) + " |")
    lines.extend(
        [
            "",
            "## Payload-specific conclusions",
            "",
            "- PyAV, FFmpeg, x264, x265, and their codec DLLs are not part of the reviewed rebuilt payload.",
            "- PyTorch and external AI candidate weights are not bundled.",
            "- NVIDIA cuBLAS/cuBLASLt, NVRTC, and cuDNN runtime DLLs are bundled under NVIDIA's SDK distribution terms and require the supplied terms/notices to accompany the application.",
            "- Intel oneMKL code and the Intel OpenMP runtime arrive through the CTranslate2 wheel; the Intel Simplified Software License permits unmodified binary redistribution with its copyright and terms reproduced.",
            "- CPython's included license expressly addresses redistribution of its Windows binary build and embedded Microsoft Distributable Code; its conditions are carried into the notice bundle.",
            root_license_conclusion,
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", type=Path, default=Path("dist/payload"))
    parser.add_argument("--installer", type=Path, default=Path("dist/LiveSub-Setup.exe"))
    parser.add_argument("--output-dir", type=Path, default=Path("release"))
    args = parser.parse_args()
    workspace = Path(__file__).resolve().parents[1]
    payload = (workspace / args.payload).resolve() if not args.payload.is_absolute() else args.payload
    installer = (workspace / args.installer).resolve() if not args.installer.is_absolute() else args.installer
    output = (workspace / args.output_dir).resolve() if not args.output_dir.is_absolute() else args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    sbom = build_sbom(workspace, payload, installer)
    json_path = output / "SBOM-v0.1.0-preview.json"
    md_path = output / "SBOM-v0.1.0-preview.md"
    json_path.write_text(json.dumps(sbom, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(sbom, payload, installer), encoding="utf-8")
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
