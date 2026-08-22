# LiveSub third-party notices

This notice covers the staged Windows payload for **LiveSub v0.1.0 Preview**. The machine-readable inventory is [`release/SBOM-v0.1.0-preview.json`](release/SBOM-v0.1.0-preview.json); the human-readable inventory is [`release/SBOM-v0.1.0-preview.md`](release/SBOM-v0.1.0-preview.md). Those files are generated from the actual payload and Windows Cargo graph by `tools/generate_release_sbom.py`.

This is an engineering compliance record, not legal advice. Third-party software and model licenses remain separate from the LiveSub application source license.

## LiveSub source-license status

`Cargo.toml` declares MIT, but repository history identifies only the GitHub account `dashqqq`; it does not establish the legal copyright-holder text the owner wants in a root MIT license. A root `LICENSE` has therefore not been invented. The project owner must supply or approve the exact copyright line before the source-license inconsistency is cleared.

## Shipped model artifacts

| Artifact | Exact provenance | License / basis | Required treatment |
| --- | --- | --- | --- |
| SYSTRAN `faster-whisper-small` | `Systran/faster-whisper-small` revision `536b0662742c02347bc0e980a01041f333bce120` | MIT; the model card identifies it as a CTranslate2 conversion of `openai/whisper-small` | Preserve SYSTRAN conversion and OpenAI Whisper MIT notices |
| Silero VAD graph | `silero_vad_v6.onnx` supplied by faster-whisper `v1.2.1`; asset introduced by faster-whisper commit `dea24cbcc6cbef23ff599a63be0bbb647a0b23d6`; upstream Silero release `v6.0` | MIT | Preserve faster-whisper and Silero notices |

Model hashes are recorded and verified by the SBOM generator. The principal model weight is:

```text
model.bin
SHA-256 3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671
```

Qwen, IndicTrans2, OPUS/Marian, M2M100, NLLB and other registry candidates are not shipped in this Preview. Registry metadata does not make a model part of the installer.

## Principal shipped runtimes

| Component | Version / revision | License | Distribution treatment |
| --- | --- | --- | --- |
| CPython embeddable x64 | 3.12.10 | PSF License Version 2 plus incorporated notices | Preserve `python/LICENSE.txt`; obey its Windows Microsoft Distributable Code conditions |
| faster-whisper | 1.2.1 / tag commit `65882eee9f5cdbeeb2d877f1131d48cf241b327d` | MIT | Preserve license |
| CTranslate2 | 4.8.1 / tag commit `399239a790ad0da4e4363e0dcbb83495b5abd742` | MIT plus native third-party terms below | Preserve CTranslate2 and native notices |
| ONNX Runtime | 1.29.0 | MIT plus included third-party notices | Preserve `LICENSE` and `ThirdPartyNotices.txt` |
| Intel oneMKL | 2025.3.0.372 build provenance; exact notice set obtained from official 2025.3.0.453 static redistributable package | Intel Simplified Software License plus included third-party terms | Unmodified binary redistribution; reproduce Intel terms and relevant notices |
| Intel OpenMP runtime | 2025.3, binary file version `20250910` | Intel Simplified Software License plus included third-party terms | Exact bundled DLL hash matches Intel NuGet `intelopenmp.redist.win` 2025.3.0.640; reproduce terms/notices |
| oneDNN | 3.1.1, statically linked by CTranslate2 wheel | Apache-2.0 | Preserve license and notices |
| NVIDIA cuBLAS/cuBLASLt | 12.9.2.10 | NVIDIA SDK License Agreement | Named redistributables; accompany with supplied terms |
| NVIDIA NVRTC | 12.9.86 | NVIDIA SDK License Agreement | Named redistributables; accompany with supplied terms |
| NVIDIA cuDNN | 9.24.0.43 runtime plus CTranslate2 compatibility DLL 9.10.2.21 | NVIDIA SDK License Agreement and cuDNN Supplement | Runtime `.dll` redistribution under the agreement; accompany with supplied terms |
| Microsoft VC runtime | 14.42.34438.0 in CPython payload | Microsoft Distributable Code terms referenced by CPython | Windows-only, unmodified runtime distribution; preserve notices/restrictions |
| Inno Setup | 6.7.3 | Inno Setup License | Use, including commercial use, and generated installer distribution permitted under the license; acknowledgment appreciated, not required |

The exact NVIDIA package license files are carried from each installed wheel. The CUDA 12.9 Attachment A identifies Windows `cublas.dll`, `cublasLt.dll`, `nvblas.dll`, `nvrtc.dll`, and `nvrtc-builtins.dll` (including versioned filename variants) as distributable. The current cuDNN supplement identifies runtime `.dll` files as distributable. LiveSub adds material application functionality and uses the libraries only through its inference runtime.

## CTranslate2 native provenance

The CTranslate2 4.8.1 Windows wheel build is pinned by its upstream release workflow:

- CUDA Toolkit 12.8.1 was used to compile GPU support with dynamic CUDA loading;
- cuDNN 9.10.2 supplied the signed compatibility DLL included by CTranslate2;
- Intel oneAPI Base Toolkit 2025.3.0.372 supplied the statically linked oneMKL backend and Intel OpenMP runtime;
- oneDNN 3.1.1 was built statically for inference;
- CTranslate2 submodules were pinned to their exact Git commits in the SBOM.

The wheel itself does not contain a collected native notices directory. LiveSub fills that gap with the exact upstream texts in `licenses/native/` and the matching official Intel redistribution-package texts in `licenses/intel/`. The bundled `libiomp5md.dll` and Intel's official `intelopenmp.redist.win` 2025.3.0.640 DLL both have SHA-256:

```text
982233366b0afcda1e0f55a0b134097e35b779613f54ddb69e685e6cd06b755f
```

Additional CTranslate2 code incorporated into the native DLL uses permissive terms, including BS thread pool (MIT), cpu_features (Apache-2.0), CUTLASS (BSD-3-Clause), cxxopts (MIT), ruy (Apache-2.0), spdlog (MIT), Thrust/CCCL (Apache-2.0), and Julien Pommier SIMD math functions (zlib).

Julien Pommier SIMD math-function notice:

> Copyright (C) 2011 Julien Pommier. This software is provided as-is, without express or implied warranty. Permission is granted to use it for any purpose, including commercial applications, and to alter and redistribute it freely, provided the origin is not misrepresented, altered source versions are plainly marked, and this notice is not removed from a source distribution. This is the zlib license.

## Python packages

The SBOM enumerates every installed Python distribution from the payload's `*.dist-info/METADATA`. The build copies the license, notice, copying, authors and unlicense files supplied by those distributions into `licenses/python-packages/` inside the installed application. Packages that contain native libraries are separately represented in the native/model sections where needed.

The rebuilt consumer payload intentionally excludes PyAV, FFmpeg, x264, x265 and the other media-codec DLLs previously pulled in by PyAV. LiveSub's worker receives decoded float32 PCM from WASAPI and does not use media-file decoding. PyTorch is also not bundled.

No packaged dependency was classified as GPL, AGPL, SSPL, research-only, non-commercial-only or unknown after the payload rebuild. Certifi and tqdm carry MPL terms; their supplied license texts and unmodified source files are included. NVIDIA packages remain governed by their named proprietary redistribution agreements rather than being treated as open-source packages.

## Rust crates

The build collects notices from every crate reachable through the Windows-filtered normal dependency graph in `Cargo.lock`. Dev dependencies and build-only crates are not represented as runtime components. The generated SBOM lists the exact crate versions and license expressions, and `licenses/rust-crates/` inside the installed application carries the source packages' applicable license/notice files.

The audited runtime graph contains permissive licenses such as MIT, Apache-2.0, BSD, ISC, Unicode-3.0, Zlib, BSL-1.0, Unlicense and font licenses. It contains no GPL, AGPL, SSPL, non-commercial or unknown license expression.

## Installer technology

LiveSub Setup is generated with Inno Setup 6.7.3. Its bundled license states that anyone may use the software for any purpose, including commercial applications, subject to its conditions. The separate official purchase page requests that commercial users purchase a license; that request does not replace or narrow the distribution grant in `license.txt`. Building the Preview is therefore classified `CLEARED WITH NOTICE`; purchasing an Inno commercial-support license remains a business/support action before commercial operation, not a restriction on distributing this non-commercial Preview.

## Where full texts are installed

The generated installer includes:

```text
licenses/
  THIRD_PARTY_NOTICES.md
  LICENSES-MANIFEST.sha256
  reviewed/intel/
  reviewed/native/
  python-packages/
  rust-crates/
```

CPython's complete combined license remains at `python/LICENSE.txt`; ONNX Runtime also retains its package-local license and third-party notices. `LICENSES-MANIFEST.sha256` hashes every collected notice so omissions or accidental modifications can be detected.

## Evidence links

- CTranslate2 4.8.1 source and build workflow: <https://github.com/OpenNMT/CTranslate2/tree/v4.8.1>
- faster-whisper 1.2.1: <https://github.com/SYSTRAN/faster-whisper/tree/v1.2.1>
- exact model revision: <https://huggingface.co/Systran/faster-whisper-small/tree/536b0662742c02347bc0e980a01041f333bce120>
- Silero VAD v6 upstream release: <https://github.com/snakers4/silero-vad/releases/tag/v6.0>
- NVIDIA CUDA 12.9 EULA: <https://docs.nvidia.com/cuda/archive/12.9.1/eula/contents.html>
- NVIDIA cuDNN license supplement: <https://docs.nvidia.com/deeplearning/cudnn/backend/reference/eula.html>
- Intel oneMKL redistribution FAQ: <https://www.intel.com/content/www/us/en/developer/articles/tool/onemkl-license-faq.html>
- Microsoft C++ runtime deployment: <https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files>
- Inno Setup license/purchase information: <https://jrsoftware.org/isinfo.php> and <https://jrsoftware.org/ishelp/topic_purchase.htm>
