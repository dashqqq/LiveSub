param(
    [string]$PythonPath = "python",
    [ValidateSet("tiny", "base", "small", "medium", "large-v3")]
    [string]$Model = "small",
    [switch]$EnableCuda
)

$workspace = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$venv = Join-Path $workspace ".venv\Scripts\python.exe"
$requirements = Join-Path $workspace "ai_worker\requirements.txt"
$cudaRequirements = Join-Path $workspace "ai_worker\requirements-cuda.txt"
$modelDirectory = Join-Path $workspace "models"

& $PythonPath -m venv (Join-Path $workspace ".venv")
if ($LASTEXITCODE -ne 0) { throw "Could not create the LiveSub Python environment" }

& $venv -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Could not update pip" }
& $venv -m pip install -r $requirements
if ($LASTEXITCODE -ne 0) { throw "Could not install LiveSub AI dependencies" }
if ($EnableCuda) {
    & $venv -m pip install -r $cudaRequirements
    if ($LASTEXITCODE -ne 0) { throw "Could not install LiveSub CUDA dependencies" }
}

$download = "from faster_whisper import WhisperModel; WhisperModel('$Model', device='cpu', compute_type='int8', download_root=r'$modelDirectory'); print('MODEL_READY=$Model')"
& $venv -c $download
if ($LASTEXITCODE -ne 0) { throw "Could not download the $Model model" }

Write-Output "AI_ENVIRONMENT_READY=$venv"
