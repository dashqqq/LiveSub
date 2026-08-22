param(
    [Parameter(Mandatory = $true)]
    [string]$Path,
    [int]$DurationSeconds = 0
)

Add-Type -AssemblyName System
$player = New-Object System.Media.SoundPlayer $Path
if ($DurationSeconds -gt 0) {
    $player.PlayLooping()
    Start-Sleep -Seconds $DurationSeconds
    $player.Stop()
}
else {
    $player.PlaySync()
}
