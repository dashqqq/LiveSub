# Third-party notices and release inventory

LiveSub depends on third-party software and model artifacts. This document is an engineering inventory for the current `0.1.0` Preview payload; it is not a legal opinion and does not replace the license texts that must accompany a distributable build.

## Source-license status

`Cargo.toml` currently declares the LiveSub application source as MIT, but the repository has no root `LICENSE` text. The project owner must resolve that inconsistency before treating this as a public source license grant.

## Bundled model and VAD

| Component | Pinned version/revision | Recorded license | Role |
| --- | --- | --- | --- |
| [SYSTRAN faster-whisper-small](https://huggingface.co/Systran/faster-whisper-small) | `536b0662742c02347bc0e980a01041f333bce120` | MIT | Multilingual ASR/translation model |
| [Silero VAD](https://github.com/snakers4/silero-vad) | graph supplied by faster-whisper 1.2.1; registry candidate pinned to `7e30209a3e901f9842f81b225f3e93d8199902b1` | MIT | Voice activity detection |

The local model snapshot used for the reviewed build does not itself contain a complete collected notices directory. Before public binary distribution, the release process must include the applicable upstream license texts and confirm the model revision’s redistribution terms directly from upstream—not only repository metadata.

## Bundled Python/native runtime

The reviewed Windows payload is built from `ai_worker/requirements-windows-runtime.txt`. Principal shipped components include:

| Component | Version | Package metadata / upstream license indication |
| --- | --- | --- |
| faster-whisper | 1.2.1 | MIT |
| CTranslate2 | 4.8.1 | MIT |
| ONNX Runtime | 1.29.0 | MIT |
| Hugging Face Hub | 1.28.0 | Apache-2.0 |
| tokenizers | 0.23.1 | Apache-2.0 classifier |
| PyAV | 18.1.0 | requires review together with bundled FFmpeg libraries |
| NumPy | 2.5.2 | BSD-family upstream license; shipped notices must be retained |
| cryptography / cffi | 50.0.0 / 2.1.1 | upstream license files must be retained |
| NVIDIA cuBLAS | 12.9.2.10 | NVIDIA proprietary redistribution terms apply |
| NVIDIA CUDA NVRTC | 12.9.86 | package metadata: LicenseRef-NVIDIA-Proprietary |
| NVIDIA cuDNN | 9.24.0.43 | NVIDIA proprietary redistribution terms apply |

The payload also includes pinned support libraries listed in `ai_worker/requirements-windows-runtime.txt` and Python’s embeddable runtime. PyAV contains native media libraries, so their exact build configuration and LGPL/GPL/codec notice implications must be audited from the actual wheel payload before release. Do not infer clearance from a blank Python metadata `License` field.

## Rust application

Rust dependencies are pinned by `Cargo.lock`. They include the Windows bindings, eframe/egui UI stack, tracing, crossbeam channels, serialization, and supporting crates. The release must generate a complete notices bundle from the exact locked dependency graph and preserve every required license text before binary publication.

## Installer technology

The current build is produced with Inno Setup. Its official [commercial licensing page](https://jrsoftware.org/isorder.php) requests a license for commercial users. The reviewed compiler identified itself as a non-commercial installation. Appropriate commercial-use status/approval must be documented before publishing a commercial LiveSub installer.

## Evaluation candidates not shipped by default

Registry entries for Qwen3-ASR, Whisper large-v3, OPUS/Marian translators, M2M100, MADLAD, IndicTrans2, and NLLB are evaluation metadata. Their presence does not mean their weights are in the installer. Each candidate must undergo its own upstream license, commercial-use, redistribution, provenance, remote-code, and notice review before inclusion in a Language Pack.

The development registry explicitly identifies restricted or blocked candidates where known; for example, non-commercial licensing or required unreviewed remote code prevents automatic packaging.

## Open release gate

A complete, payload-derived third-party notices bundle and documented redistribution approval are still open. Consequently, this repository must not claim that the current installer is cleared for public commercial distribution.
