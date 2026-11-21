# Creates "Skopje 242.lnk" (game icon) in the game folder and on the desktop; run.bat calls this once.
# trafficSimulator.bat calls it with -Name "Skopje 242 Traffic Lab" -Bat trafficSimulator.bat -Style 1 for the lab's shortcut.
param([string]$Game = (Split-Path -Parent $PSScriptRoot), [string]$Name = "Skopje 242", [string]$Bat = "run.bat", [int]$Style = 7)
try {
    $sh = New-Object -ComObject WScript.Shell
    $targets = @((Join-Path $Game "$Name.lnk"))
    $desk = [Environment]::GetFolderPath("Desktop")
    if ($desk) { $targets += (Join-Path $desk "$Name.lnk") }
    foreach ($p in $targets) {
        $l = $sh.CreateShortcut($p)
        $l.TargetPath = Join-Path $Game $Bat
        $l.WorkingDirectory = $Game
        $l.IconLocation = (Join-Path $Game "assets\icon.ico") + ",0"
        $l.WindowStyle = $Style
        $l.Description = $Name
        $l.Save()
    }
} catch { }
