param(
    [string]$PythonPath = "python",
    [string]$ModelDirectory = "models",
    [string]$InnoCompiler = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
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

if (-not (Test-Path (Join-Path $workspace "target\release\livesub.exe") -PathType Leaf)) {
    throw "Release executable is missing. Run cargo build --release first."
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
Get-ChildItem $sourcePythonRoot -File | Copy-Item -Destination $payloadPython
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
& $sourcePython -m pip install --disable-pip-version-check --no-compile --target $payloadPackages `
    -r (Join-Path $workspace "ai_worker\requirements-windows-runtime.txt")
if ($LASTEXITCODE -ne 0) { throw "Could not assemble the private Python runtime" }

# Catch missing source modules and signing dependencies before producing an
# installer. This runs from the exact private runtime tree that will ship.
Push-Location $payload
try {
    & (Join-Path $payloadPython "python.exe") -c "import ai_worker.worker, ai_worker.language_id, ai_worker.language_packs; from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey"
    if ($LASTEXITCODE -ne 0) { throw "Packaged inference/security import smoke test failed" }
} finally {
    Pop-Location
}

New-Item -ItemType Directory -Path (Join-Path $payload "models") -Force | Out-Null
Copy-Item $smallModel (Join-Path $payload "models") -Recurse

$buildInfo = @(
    "LiveSub 0.1.0",
    "Model: faster-whisper small",
    "Inference: CUDA/float16 AUTO with CPU/int8 fallback",
    "Audio: Windows WASAPI loopback",
    "Privacy: local processing"
) -join [Environment]::NewLine
[System.IO.File]::WriteAllText((Join-Path $payload "BUILD-INFO.txt"), $buildInfo)

& $InnoCompiler "/DPayloadDir=$payload" "/DOutputDir=$dist" (Join-Path $workspace "installer\LiveSub.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup compilation failed" }

$installer = Join-Path $dist "LiveSub-Setup.exe"
if (-not (Test-Path $installer -PathType Leaf)) { throw "Installer output is missing" }
Get-Item $installer | Select-Object FullName, Length, LastWriteTime
