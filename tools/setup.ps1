# One-time / incremental setup for Skopje 242. Called by run.bat. ASCII only on purpose.
param([switch]$Demo, [switch]$Refresh, [switch]$AiVoice)
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$rt = Join-Path $root '.runtime'
New-Item -ItemType Directory -Force -Path $rt | Out-Null
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}

$script:step = 0
$script:steps = 4
function Say($m) { Write-Host "[setup] $m" }
function Step($name) {
    $script:step++
    $pct = [int](100 * ($script:step - 1) / $script:steps)
    Write-Progress -Activity "Skopje 242 setup" -Status "step $($script:step)/$($script:steps): $name" -PercentComplete $pct
    Write-Host ""
    Write-Host ("=== [{0}/{1}] {2} ===" -f $script:step, $script:steps, $name)
}

# ---------------------------------------------------------------- python
Step 'Python runtime'
function Test-Python($exe, $pre) {
    try {
        $out = & $exe @pre -c "import sys;print(sys.version_info[0]*100+sys.version_info[1]);print(sys.maxsize>2**32);print(sys.executable)" 2>$null
        if ($LASTEXITCODE -ne 0 -or $out.Count -lt 3) { return $null }
        if ([int]$out[0] -lt 309 -or [int]$out[0] -gt 313 -or $out[1] -ne 'True') { return $null }
        return $out[2]
    } catch { return $null }
}

$py = $null
if (Test-Path "$rt\venv\Scripts\python.exe") { $py = "$rt\venv\Scripts\python.exe" }
elseif (Test-Path "$rt\python\python.exe") { $py = "$rt\python\python.exe" }
else {
    $sys = $null
    foreach ($c in @(@{e='py'; a=@('-3.12')}, @{e='py'; a=@('-3.13')}, @{e='py'; a=@('-3.11')}, @{e='py'; a=@('-3')}, @{e='python'; a=@()}, @{e='python3'; a=@()})) {
        if (-not (Get-Command $c.e -ErrorAction SilentlyContinue)) { continue }
        $sys = Test-Python $c.e $c.a
        if ($sys) { break }
    }
    if ($sys) {
        Say "Using system Python: $sys"
        & $sys -m venv "$rt\venv" 2>$null
        if ($LASTEXITCODE -eq 0 -and (Test-Path "$rt\venv\Scripts\python.exe")) { $py = "$rt\venv\Scripts\python.exe" }
        else { Say "venv creation failed, falling back to a private Python" }
    }
    if (-not $py) {
        Say "Downloading a private Python 3.12 (about 10 MB) ..."
        $zip = "$rt\python-embed.zip"
        Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/3.12.8/python-3.12.8-embed-amd64.zip' -OutFile $zip
        Expand-Archive -Force -Path $zip -DestinationPath "$rt\python"
        $pth = Get-ChildItem "$rt\python" -Filter 'python*._pth' | Select-Object -First 1
        (Get-Content $pth.FullName) -replace '^#import site', 'import site' | Set-Content $pth.FullName
        Invoke-WebRequest -UseBasicParsing -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile "$rt\get-pip.py"
        & "$rt\python\python.exe" "$rt\get-pip.py" --no-warn-script-location
        if ($LASTEXITCODE -ne 0) { Say "pip installation failed"; exit 1 }
        $py = "$rt\python\python.exe"
    }
}

# ---------------------------------------------------------------- libraries
Step 'Libraries'
& $py -c "import pyray, numpy, PIL, mapbox_earcut" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Say "Installing libraries (raylib, numpy, pillow, mapbox-earcut) ..."
    & $py -m pip install --disable-pip-version-check --no-warn-script-location -r "$root\requirements.txt"
    if ($LASTEXITCODE -ne 0) {
        Say "pip install failed - retrying once (upgrading pip first) ..."
        & $py -m pip install --upgrade pip 2>$null | Out-Null
        & $py -m pip install --disable-pip-version-check --no-warn-script-location --prefer-binary -r "$root\requirements.txt"
        if ($LASTEXITCODE -ne 0) { Say "pip install failed twice. Check your internet connection and run run.bat again."; exit 1 }
    }
}
& $py -c "import osmium" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Say "Installing pyosmium (reads the Geofabrik map file; optional - Overpass is used without it) ..."
    & $py -m pip install --disable-pip-version-check --no-warn-script-location --prefer-binary osmium
    if ($LASTEXITCODE -ne 0) { Say "pyosmium could not be installed - the map will come from Overpass." }
}
# the Macedonian voice: Suze for RHVoice, through Windows speech (SAPI); a failure never blocks the game
Step 'Voice (Suze, RHVoice)'
& $py -c "import comtypes" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { & $py -m pip install --disable-pip-version-check --no-warn-script-location comtypes }
& $py "$root\src\speech.py" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0 -and (Test-Path "$root\tools\rhvoice_urls.txt")) {
    Say "Installing the Macedonian voice Suze (RHVoice engine + voice, Windows may ask for permission) ..."
    $dl = "$rt\rhvoice"; New-Item -ItemType Directory -Force -Path $dl | Out-Null
    foreach ($u in (Get-Content "$root\tools\rhvoice_urls.txt" | Where-Object { $_ -match '^https://' })) {
        $f = Join-Path $dl ([IO.Path]::GetFileName(([Uri]$u).AbsolutePath))
        if (-not (Test-Path $f)) {
            try { Invoke-WebRequest -UseBasicParsing -Uri $u -OutFile "$f.part"; Move-Item -Force "$f.part" $f }
            catch { Say "Could not download $u"; continue }
        }
        if ($f -like '*.msi') { Start-Process msiexec.exe -ArgumentList "/i `"$f`" /qn /norestart" -Wait -Verb RunAs }
        else { Start-Process $f -ArgumentList '/S' -Wait -Verb RunAs }
    }
    & $py "$root\src\speech.py"
    if ($LASTEXITCODE -ne 0) { Say "Suze is not available - the built-in voice is used. Run run.bat again to retry." }
}
Set-Content -Path "$rt\python.txt" -Value $py -Encoding ASCII

Write-Progress -Activity "Skopje 242 setup" -Completed
Say "Ready - starting the game (the map is downloaded and built inside the game window, with a progress screen)."
exit 0
