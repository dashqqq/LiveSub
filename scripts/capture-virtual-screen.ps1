param(
    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$bounds = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bitmap = New-Object System.Drawing.Bitmap($bounds.Width, $bounds.Height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
try {
    $graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
    $resolved = [System.IO.Path]::GetFullPath($OutputPath)
    $bitmap.Save($resolved, [System.Drawing.Imaging.ImageFormat]::Png)
    Write-Output $resolved
}
finally {
    $graphics.Dispose()
    $bitmap.Dispose()
}
