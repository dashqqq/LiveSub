# LiveSub development

These instructions are for maintainers and testers. End users should install a GitHub Release when one is available; they should not need this toolchain.

## Prerequisites

- Windows 10 or Windows 11, 64-bit
- Rust with the MSVC target/toolchain
- Python 3.10–3.12, 64-bit
- PowerShell
- a working Windows render endpoint for audio tests
- optional compatible NVIDIA hardware for CUDA testing
- Inno Setup only for installer engineering, subject to the release/licensing gate below

## Create the inference environment

From the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-ai.ps1 -PythonPath python -Model small
```

For a CUDA development environment, add `-EnableCuda`. The script creates `.venv`, installs the pinned AI requirements, and downloads the selected model into `models/`. Both directories are intentionally excluded from Git.

## Build and run

```powershell
cargo build --release
.\target\release\livesub.exe desktop --start
```

Useful diagnostics:

```powershell
cargo run -- list-audio
cargo run -- probe-audio --seconds 10
cargo run -- run-live --python .venv\Scripts\python.exe --model base --seconds 30
cargo run -- desktop --start
```

Normal execution does not download a missing model. `run-live` has an explicit `--allow-model-download` option for controlled development only; curated staging is preferred.

## Tests

```powershell
cargo fmt --check
cargo test --quiet
cargo clippy --all-targets -- -D warnings
.\.venv\Scripts\python.exe -m unittest discover -s benchmarks/tests -p test_*.py
.\.venv\Scripts\python.exe -m compileall ai_worker benchmarks tools
```

The test commands above cover deterministic native and Python units. WASAPI, model warm-up, real media, overlay composition, clean-machine installation, and long-run stability require separate Windows acceptance runs; unit tests are not a substitute.

## Benchmark harness

```powershell
.\.venv\Scripts\python.exe benchmarks\evaluate.py validate
.\.venv\Scripts\python.exe benchmarks\evaluate.py validate --strict
```

Strict validation is expected to fail until human-approved references exist. This is an evidence gate, not a broken command. Model-specific ASR and translation examples are documented in [../benchmarks/README.md](../benchmarks/README.md).

Do not enable remote model code in the consumer process. Candidate models must be staged through reviewed tooling, pinned to a revision, hashed, and evaluated without silently substituting generated text for human gold.

## Package engineering build

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\package-windows.ps1 -PythonPath python -ModelDirectory models
```

The packaging script invokes `scripts/build-release.ps1` itself. That release
build remaps machine-local workspace and profile paths before compiling the
binary; do not substitute a stale `target\release\livesub.exe`.

The packaging script assembles a private Python runtime, runs packaged
import/security smoke tests, copies the pinned small model, collects the actual
payload license texts, audits the staged files, and invokes Inno Setup. It
writes `dist/LiveSub-Setup.exe`, which is ignored by Git and belongs in GitHub
Releases only. It also writes the checksum, payload-audit report, and Preview
SBOM under `release/`.

The collector and SBOM generator can also be checked independently against an
already staged payload:

```powershell
python .\tools\collect_release_licenses.py --payload .\dist\payload
python .\tools\audit_release_payload.py --payload .\dist\payload --report .\release\payload-audit-v0.1.0-preview.json
python .\tools\generate_release_sbom.py --payload .\dist\payload --installer .\dist\LiveSub-Setup.exe --output-dir .\release
```

Do not publicly redistribute the generated installer until the root LiveSub
source-license grant, final payload audit, bundled dependency/model notices,
and Preview smoke gates are cleared. See
[release-process.md](release-process.md).

## Code and review expectations

- Preserve bounded queues and nonblocking capture.
- Add tests for subtitle revisions, overlap, LID stability, semantic checks, and download integrity when changing those paths.
- Never promote a model based only on a model card.
- Do not add secrets, private recordings, browser profiles, models, build output, or installer payloads to Git.
- Keep user-facing claims tied to executed evidence.
- Accuracy changes require per-language regression review and live latency/resource checks.
