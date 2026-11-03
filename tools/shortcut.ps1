# Creates "Skopje 242.lnk" (game icon) in the game folder and on the desktop; run.bat calls this once.
param([string]$Game = (Split-Path -Parent $PSScriptRoot))
try {
    $sh = New-Object -ComObject WScript.Shell
    $targets = @((Join-Path $Game "Skopje 242.lnk"))
    $desk = [Environment]::GetFolderPath("Desktop")
    if ($desk) { $targets += (Join-Path $desk "Skopje 242.lnk") }
    foreach ($p in $targets) {
        $l = $sh.CreateShortcut($p)
        $l.TargetPath = Join-Path $Game "run.bat"
        $l.WorkingDirectory = $Game
        $l.IconLocation = (Join-Path $Game "assets\icon.ico") + ",0"
        $l.WindowStyle = 7
        $l.Description = "Skopje 242"
        $l.Save()
    }
} catch { }
