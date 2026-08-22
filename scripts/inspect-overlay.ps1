Add-Type @'
using System;
using System.Runtime.InteropServices;

public static class LiveSubWindowInspection {
    private delegate bool EnumWindowsCallback(IntPtr window, IntPtr parameter);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern IntPtr FindWindow(string className, string windowName);

    [DllImport("user32.dll")]
    private static extern bool EnumWindows(EnumWindowsCallback callback, IntPtr parameter);

    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr window, out uint processId);

    [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")]
    public static extern IntPtr GetWindowLongPtr64(IntPtr window, int index);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool IsWindowVisible(IntPtr window);

    public static IntPtr FindLayeredWindow(uint wantedProcessId) {
        IntPtr found = IntPtr.Zero;
        EnumWindows(delegate (IntPtr window, IntPtr parameter) {
            uint processId;
            GetWindowThreadProcessId(window, out processId);
            long style = GetWindowLongPtr64(window, -20).ToInt64();
            if (processId == wantedProcessId && (style & 0x00080000) != 0) {
                found = window;
                return false;
            }
            return true;
        }, IntPtr.Zero);
        return found;
    }
}
'@

$window = [LiveSubWindowInspection]::FindWindow($null, "LiveSub Overlay")
if ($window -eq [IntPtr]::Zero) {
    $process = Get-Process -Name livesub -ErrorAction Stop | Select-Object -First 1
    $window = [LiveSubWindowInspection]::FindLayeredWindow([uint32]$process.Id)
}
if ($window -eq [IntPtr]::Zero) {
    throw "LiveSub layered overlay window was not found"
}
$style = [LiveSubWindowInspection]::GetWindowLongPtr64($window, -20).ToInt64()
[PSCustomObject]@{
    Visible = [LiveSubWindowInspection]::IsWindowVisible($window)
    Layered = ($style -band 0x00080000) -ne 0
    ToolWindow = ($style -band 0x00000080) -ne 0
    TopMost = ($style -band 0x00000008) -ne 0
    NoActivate = ($style -band 0x08000000) -ne 0
    ClickThrough = ($style -band 0x00000020) -ne 0
    ExtendedStyle = ('0x{0:X8}' -f $style)
}
