param(
    [string]$PythonPath = "python",
    [string]$ModelDirectory = "models",
    [string]$InnoCompiler = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    [switch]$AllowMissingRootLicense
)

$ErrorActionPreference = "Stop"
$workspace = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$dist = Join-Path $workspace "dist"
$payload = Join-Path $dist "payload"
$payloadPython = Join-Path $payload "python"
$payloadPackages = Join-Path $payloadPython "Lib\site-packages"
$sourcePython = (Get-Command $PythonPath -ErrorAction Stop).Source
$sourcePythonRoot = Split-Path $sourcePython -Parent
$sourceModelRoot = [System.IO.Path]::GetFullPath((Join-Path $workspace $ModelDirectory))
$smallModel = Join-Path $sourceModelRoot "models--Systran--faster-whisper-small"
$rootLicense = Join-Path $workspace "LICENSE"

$requiredPythonFiles = @(
    "python.exe",
    "pythonw.exe",
    "python312.dll",
    "python312.zip",
    "python312._pth",
    "LICENSE.txt"
)
foreach ($requiredPythonFile in $requiredPythonFiles) {
    if (-not (Test-Path (Join-Path $sourcePythonRoot $requiredPythonFile) -PathType Leaf)) {
        throw "Python runtime source is not the required CPython 3.12.10 embeddable layout: missing $requiredPythonFile"
    }
}

if (-not (Test-Path $rootLicense -PathType Leaf) -and -not $AllowMissingRootLicense) {
    throw "Root LICENSE is missing. The owner must approve the LiveSub source license before a redistributable build."
}
if (Test-Path $rootLicense -PathType Leaf) {
    $rootLicenseText = [System.IO.File]::ReadAllText($rootLicense)
    if ($rootLicenseText -notmatch '(?m)^MIT License\s*$' -or
        $rootLicenseText -notmatch 'Permission is hereby granted, free of charge') {
        throw "Root LICENSE does not contain the expected canonical MIT grant declared by Cargo.toml."
    }
}

# Rebuild with machine-local source paths remapped before staging. This avoids
# copying a stale executable and prevents the release binary from exposing the
# build user's profile/workspace paths.
& (Join-Path $workspace "scripts\build-release.ps1")
if ($LASTEXITCODE -ne 0) { throw "Could not build the release executable" }

if (-not (Test-Path (Join-Path $workspace "target\release\livesub.exe") -PathType Leaf)) {
    throw "Release executable is missing after the release build."
}
if (-not (Test-Path $smallModel -PathType Container)) {
    throw "The bundled small model is missing: $smallModel"
}
if (-not (Test-Path $InnoCompiler -PathType Leaf)) {
    throw "Inno Setup compiler is missing: $InnoCompiler"
}

if (Test-Path $payload) {
    $resolvedPayload = [System.IO.Path]::GetFullPath($payload)
    $expectedPayload = [System.IO.Path]::GetFullPath((Join-Path $workspace "dist\payload"))
    if ($resolvedPayload -ne $expectedPayload) {
        throw "Refusing to remove unexpected payload directory: $resolvedPayload"
    }
    Remove-Item -LiteralPath $resolvedPayload -Recurse -Force
}

New-Item -ItemType Directory -Path $payloadPackages -Force | Out-Null
Copy-Item (Join-Path $workspace "target\release\livesub.exe") $payload
Copy-Item (Join-Path $workspace "README.md") $payload
if (Test-Path $rootLicense -PathType Leaf) {
    Copy-Item $rootLicense $payload
}
New-Item -ItemType Directory -Path (Join-Path $payload "ai_worker") -Force | Out-Null
$workerFiles = @(
    "__init__.py",
    "worker.py",
    "language_id.py",
    "language_packs.py"
)
foreach ($workerFile in $workerFiles) {
    Copy-Item (Join-Path $workspace "ai_worker\$workerFile") (Join-Path $payload "ai_worker")
}
Copy-Item (Join-Path $workspace "ai_worker\engines") (Join-Path $payload "ai_worker") -Recurse
Copy-Item (Join-Path $workspace "ai_worker\translation") (Join-Path $payload "ai_worker") -Recurse
Copy-Item (Join-Path $workspace "registry") $payload -Recurse

# The source is Python's embeddable distribution. Copy only its runtime files;
# pip then reconstructs an isolated, dependency-minimal site-packages tree.
Get-ChildItem -LiteralPath $sourcePythonRoot -File | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $payloadPython
}
$pathConfiguration = Get-ChildItem $payloadPython -Filter "python*._pth" -File
if ($pathConfiguration.Count -ne 1) {
    throw "Expected exactly one embeddable Python path configuration"
}
$pathLines = [System.Collections.Generic.List[string]]::new()
$pathLines.AddRange([string[]][System.IO.File]::ReadAllLines($pathConfiguration.FullName))
if (-not $pathLines.Contains("..")) {
    $siteIndex = $pathLines.IndexOf("import site")
    if ($siteIndex -lt 0) { throw "Embeddable Python path file does not enable site" }
    $pathLines.Insert($siteIndex, "..")
    [System.IO.File]::WriteAllLines($pathConfiguration.FullName, $pathLines)
}
& $sourcePython -m pip install --disable-pip-version-check --no-compile --no-deps --target $payloadPackages `
    -r (Join-Path $workspace "ai_worker\requirements-windows-runtime.txt")
if ($LASTEXITCODE -ne 0) { throw "Could not assemble the private Python runtime" }

# LiveSub always gives faster-whisper decoded float32 PCM arrays from WASAPI.
# Make PyAV optional so the consumer payload does not carry an unused FFmpeg
# and codec stack. File/media decoding remains intentionally unsupported by
# the private worker runtime.
$fasterWhisperAudio = Join-Path $payloadPackages "faster_whisper\audio.py"
$audioSource = [System.IO.File]::ReadAllText($fasterWhisperAudio)
$audioSource = $audioSource -replace "(?m)^import av\r?\n", @'
try:
    import av
except ModuleNotFoundError:
    av = None  # LiveSub passes decoded PCM; file decoding is not packaged.
'@
[System.IO.File]::WriteAllText($fasterWhisperAudio, $audioSource)

# pip --target emits console launchers for dependency tools. They are not used
# by LiveSub and unnecessarily widen the executable surface of the installer.
$consoleLaunchers = Join-Path $payloadPackages "bin"
if (Test-Path $consoleLaunchers -PathType Container) {
    Remove-Item -LiteralPath $consoleLaunchers -Recurse -Force
}

# Copied worker directories can contain development bytecode from local test
# runs. It is never required by the private runtime and must not ship.
Get-ChildItem -LiteralPath $payload -Recurse -Directory -Filter "__pycache__" |
    Remove-Item -Recurse -Force
Get-ChildItem -LiteralPath $payload -Recurse -File -Include "*.pyc", "*.pyo" |
    Remove-Item -Force

# Catch missing source modules and signing dependencies before producing an
# installer. This runs from the exact private runtime tree that will ship.
Push-Location $payload
try {
    & (Join-Path $payloadPython "python.exe") -c "import ai_worker.worker, ai_worker.language_id, ai_worker.language_packs, faster_whisper; from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey; assert faster_whisper.audio.av is None"
    if ($LASTEXITCODE -ne 0) { throw "Packaged inference/security import smoke test failed" }
} finally {
    Pop-Location
}

New-Item -ItemType Directory -Path (Join-Path $payload "models") -Force | Out-Null
Copy-Item $smallModel (Join-Path $payload "models") -Recurse

$buildCommit = (& git -C $workspace rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $buildCommit -notmatch '^[0-9a-f]{40}$') {
    throw "Could not record the source commit"
}
$buildTimestamp = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
$distributionClearance = if (Test-Path $rootLicense -PathType Leaf) {
    "Root application license included"
} else {
    "BLOCKED - root application LICENSE missing; engineering validation only"
}
$buildInfo = @(
    "LiveSub 0.1.0",
    "Build commit: $buildCommit",
    "Build timestamp (UTC): $buildTimestamp",
    "Python: 3.12.10 embeddable x64",
    "Model: faster-whisper small",
    "Model revision: 536b0662742c02347bc0e980a01041f333bce120",
    "Distribution clearance: $distributionClearance",
    "Inference: CUDA/float16 AUTO with CPU/int8 fallback",
    "Audio: Windows WASAPI loopback",
    "Privacy: local processing"
) -join [Environment]::NewLine
[System.IO.File]::WriteAllText((Join-Path $payload "BUILD-INFO.txt"), $buildInfo)

& $sourcePython (Join-Path $workspace "tools\collect_release_licenses.py") --payload $payload
if ($LASTEXITCODE -ne 0) { throw "Could not collect the release license bundle" }

& $sourcePython (Join-Path $workspace "tools\audit_release_payload.py") `
    --payload $payload --report (Join-Path $workspace "release\payload-audit-v0.1.0-preview.json")
if ($LASTEXITCODE -ne 0) { throw "Release payload security/privacy audit failed" }

& $InnoCompiler "/DPayloadDir=$payload" "/DOutputDir=$dist" (Join-Path $workspace "installer\LiveSub.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup compilation failed" }

$installer = Join-Path $dist "LiveSub-Setup.exe"
if (-not (Test-Path $installer -PathType Leaf)) { throw "Installer output is missing" }
$installerHash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
[System.IO.File]::WriteAllText(
    (Join-Path $workspace "release\LiveSub-Setup.exe.sha256"),
    "$installerHash  LiveSub-Setup.exe$([Environment]::NewLine)"
)
& $sourcePython (Join-Path $workspace "tools\generate_release_sbom.py") `
    --payload $payload --installer $installer --output-dir (Join-Path $workspace "release")
if ($LASTEXITCODE -ne 0) { throw "Could not generate the release SBOM" }
Get-Item $installer | Select-Object FullName, Length, LastWriteTime
