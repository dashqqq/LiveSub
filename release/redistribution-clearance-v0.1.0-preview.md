# LiveSub v0.1.0 Preview redistribution clearance

Reviewed: 2026-08-23

Scope: the rebuilt Windows installer produced from `scripts/package-windows.ps1`, not development dependencies or unbundled registry candidates. This is an engineering due-diligence record, not legal advice.

## Current decision

**Installer redistribution: CLEARED for the v0.1.0 Preview, subject to rebuilding and passing the final artifact smoke gate.**

The project owner explicitly authorized LiveSub's application source under MIT with the exact copyright line `Copyright (c) 2026 AKASH DEEP BARUAH`. The canonical root `LICENSE` now matches `Cargo.toml`. This grant applies only to LiveSub's own source; every bundled runtime, model, library, and installer component remains under the separate terms recorded below and in the SBOM.

The historical pre-audit and missing-license engineering installers must not be uploaded. The release candidate must be rebuilt without `-AllowMissingRootLicense` from the license-bearing, branding-bearing commit so the root grant, notices, icon, SBOM, checksum, and build provenance all describe the same artifact.

## Clearance matrix

| Component | License | Redistribution | Commercial use | Attribution / inclusion | Status |
| --- | --- | --- | --- | --- | --- |
| LiveSub application | MIT | Permitted by the owner-approved canonical root grant | Permitted | Include the root `LICENSE`; do not imply that it relicenses third-party payload components | **CLEARED** |
| CPython 3.12.10 embeddable x64 | PSF-2.0 plus incorporated notices | Expressly permitted subject to included terms | Permitted | Preserve `python/LICENSE.txt`; comply with Microsoft Distributable Code restrictions | **CLEARED WITH NOTICE** |
| Microsoft VC runtime 14.42.34438.0 in CPython | Microsoft Distributable Code conditions incorporated into Python Windows license | Windows local deployment permitted; Python notice expressly covers redistribution of its Windows binary build | Permitted under the terms | Do not remove notices, imply endorsement, target non-Windows platforms, or distribute in malicious/deceptive software | **CLEARED WITH NOTICE** |
| Microsoft VC runtime 14.40.33810.0 in NumPy wheel | Microsoft Distributable Code terms | Unmodified Windows runtime supplied by the wheel | Permitted under the terms | Preserve applicable Microsoft restrictions/notices | **CLEARED WITH NOTICE** |
| OpenBLAS 0.3.34.0.0 / LAPACK in NumPy 2.5.2 | BSD-3-Clause and BSD-3-Clause-Open-MPI | Binary redistribution permitted | Permitted | Reproduce the wheel's copyright, conditions, and disclaimer | **CLEARED WITH NOTICE** |
| GCC runtime code statically incorporated in NumPy OpenBLAS DLL | GPL-3.0-or-later WITH GCC-exception-3.1 | Runtime Library Exception permits distribution of the eligible compiled library without imposing GPL terms on LiveSub | Permitted under the exception | Preserve GPL and Runtime Library Exception text supplied by NumPy | **CLEARED WITH NOTICE** |
| faster-whisper 1.2.1 | MIT | Permitted | Permitted | Include SYSTRAN MIT notice | **CLEARED WITH NOTICE** |
| SYSTRAN faster-whisper-small revision `536b066...` | MIT; conversion of OpenAI Whisper small | Permitted by exact model repository and upstream Whisper MIT terms | Permitted | Include SYSTRAN/OpenAI MIT notices and provenance | **CLEARED WITH NOTICE** |
| Silero VAD v6 graph | MIT | Permitted | Permitted | Include Silero and faster-whisper notices; preserve graph provenance/hash | **CLEARED WITH NOTICE** |
| CTranslate2 4.8.1 | MIT plus native third-party terms | Permitted | Permitted | Include CTranslate2 and pinned third-party texts | **CLEARED WITH NOTICE** |
| Intel oneMKL 2025.3 | Intel Simplified Software License plus supplied third-party notices | Unmodified binary redistribution expressly permitted | Permitted | Reproduce copyright, terms, and relevant 2025.3 third-party notices | **CLEARED WITH NOTICE** |
| Intel OpenMP 2025.3 (`libiomp5md.dll`) | Intel Simplified Software License plus supplied third-party notices | Exact DLL matches official redistributable package; unmodified redistribution permitted | Permitted | Reproduce terms/notices | **CLEARED WITH NOTICE** |
| oneDNN 3.1.1 and CTranslate2 permissive subcomponents | Apache-2.0, MIT, BSD-3-Clause, Zlib as recorded | Permitted | Permitted | Preserve exact pinned licenses and notices | **CLEARED WITH NOTICE** |
| NVIDIA cuBLAS/cuBLASLt 12.9.2.10 | NVIDIA SDK License Agreement | DLL names are in CUDA 12.9 Attachment A; versioned filename variants are covered | Permitted in an application meeting distribution requirements | Include NVIDIA terms; restrict access to application use; do not imply endorsement | **CLEARED WITH NOTICE** |
| NVIDIA NVRTC 12.9.86 | NVIDIA SDK License Agreement | NVRTC and builtins DLLs are named redistributables | Permitted under agreement | Include NVIDIA terms | **CLEARED WITH NOTICE** |
| NVIDIA cuDNN 9.24.0.43 and compatibility DLL 9.10.2.21 | NVIDIA SDK License Agreement and cuDNN Supplement | Current supplement permits runtime `.dll` distribution | Permitted under agreement | Include NVIDIA/cuDNN terms | **CLEARED WITH NOTICE** |
| ONNX Runtime 1.29.0 | MIT plus package third-party notices | Permitted | Permitted | Preserve included license and `ThirdPartyNotices.txt` | **CLEARED WITH NOTICE** |
| Remaining packaged Python distributions | Permissive/MPL expressions listed individually in SBOM | Permitted under recorded terms | No non-commercial restriction found | Preserve collected package notices; MPL files remain unmodified and supplied | **CLEARED WITH NOTICE** |
| Windows runtime Rust crates | Permissive expressions listed individually in SBOM | Permitted under recorded terms | No non-commercial restriction found | Preserve collected crate notices | **CLEARED WITH NOTICE** |
| Inno Setup 6.7.3 | Inno Setup License | License permits use for any purpose and redistribution subject to conditions; generated Setup may be distributed | Commercial applications expressly permitted | Built-in copyright/site references retained; documentation acknowledgment appreciated but not required | **CLEARED WITH NOTICE** |
| PyAV / FFmpeg / x264 / x265 / media codec DLLs | Multiple, including LGPL/GPL/codec considerations | Removed because LiveSub does not use media-file decoding | Not applicable | Verify absence in rebuilt payload | **NOT BUNDLED** |
| PyTorch | Not applicable | Not shipped | Not applicable | None | **NOT BUNDLED** |
| Qwen / IndicTrans2 / OPUS / Marian / M2M100 / NLLB weights | Candidate-specific terms | Registry metadata only; no weights shipped | Not applicable to this release | Audit independently before future inclusion | **NOT BUNDLED** |

## Completed technical conditions

- Reviewed packaging and compliance inputs are committed.
- The engineering artifact contains no PyAV/FFmpeg/media-codec payload and carries 320 hash-verified notice files.
- The payload audit passes with zero findings; tracked-source secret and machine-path scans are clean; Microsoft Defender reported no threats in the final local installer.
- Rust/Python suites, CPU/int8 and CUDA/float16 warm-up, real WASAPI loopback, Russian/Japanese/Hindi translation routing, native overlay, isolated install and clean uninstall were exercised.
- The final engineering checksum and CycloneDX 1.6 SBOM were generated from the rebuilt artifact.

## Remaining conditions before publication

1. Rebuild without `-AllowMissingRootLicense` from the license-bearing, branding-bearing commit and repeat the checksum, payload, install/uninstall, and smoke gates.
2. Confirm the rebuilt SBOM has zero `BLOCKED`, `UNKNOWN`, or `OWNER REVIEW REQUIRED` bundled components.
3. Create the immutable `v0.1.0` tag, upload only the cleared artifact/checksum/SBOM to the existing draft, and publish it as a pre-release.

Code signing and full accuracy certification remain separate Stable-release work and do not alter the redistribution decision above.
