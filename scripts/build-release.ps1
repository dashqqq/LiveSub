param()

$ErrorActionPreference = "Stop"
$workspace = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$profileRoot = [Environment]::GetFolderPath("UserProfile")
$separator = [char]0x1F
$releaseFlags = [System.Collections.Generic.List[string]]::new()

if ($env:CARGO_ENCODED_RUSTFLAGS) {
    $releaseFlags.AddRange([string[]]$env:CARGO_ENCODED_RUSTFLAGS.Split($separator))
}
$releaseFlags.Add("--remap-path-prefix=$workspace=C:\livesub-src")
if ($profileRoot) {
    $releaseFlags.Add("--remap-path-prefix=$profileRoot=C:\build-user")
}

$previousFlags = $env:CARGO_ENCODED_RUSTFLAGS
try {
    $env:CARGO_ENCODED_RUSTFLAGS = $releaseFlags -join $separator
    & cargo build --release
    if ($LASTEXITCODE -ne 0) { throw "Cargo release build failed" }
} finally {
    $env:CARGO_ENCODED_RUSTFLAGS = $previousFlags
}
