Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$form = New-Object System.Windows.Forms.Form
$form.Text = "LiveSub overlay transparency test"
$form.WindowState = [System.Windows.Forms.FormWindowState]::Maximized
$form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::None
$form.BackColor = [System.Drawing.Color]::FromArgb(21, 73, 122)
$form.TopMost = $true

$title = New-Object System.Windows.Forms.Label
$title.Dock = [System.Windows.Forms.DockStyle]::Fill
$title.TextAlign = [System.Drawing.ContentAlignment]::MiddleCenter
$title.Text = "LIVE VIDEO SURFACE`r`nOverlay background must remain blue"
$title.ForeColor = [System.Drawing.Color]::FromArgb(168, 211, 255)
$title.Font = New-Object System.Drawing.Font("Segoe UI", 34, [System.Drawing.FontStyle]::Bold)
$form.Controls.Add($title)

[System.Windows.Forms.Application]::Run($form)
