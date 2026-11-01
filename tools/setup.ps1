# One-time / incremental setup for Skopje 242. Called by run.bat. ASCII only on purpose.
# Every step is logged to logs\install.log.  Hardened for: Windows 10/11 (Home/Pro/ARM), no Python, Store-Python stubs,
# broken or copied-from-another-PC venvs, spaces/OneDrive in the path, proxies, flaky downloads, missing VC++ runtime,
# files blocked by "downloaded from the internet", read-only folders, 32-bit Windows.
param([switch]$Demo, [switch]$Refresh, [switch]$AiVoice)
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$rt = Join-Path $root '.runtime'
$script:step = 0
$script:steps = 5

# ---- log first, so even folder problems are recorded
try { New-Item -ItemType Directory -Force -Path "$root\logs" | Out-Null } catch {}
try { Start-Transcript -Path "$root\logs\install.log" -Force | Out-Null } catch {}
function Say($m) { Write-Host "[setup] $m" }
function Fail($m) {
    Write-Host ""
    Write-Host "[setup] ERROR: $m"
    Write-Host "[setup] Details are in logs\install.log - send that file if you need help."
    try { Stop-Transcript | Out-Null } catch {}
    exit 1
}
function Step($name) {
    $script:step++
    $pct = [int](100 * ($script:step - 1) / $script:steps)
    Write-Progress -Activity "Skopje 242 setup" -Status "step $($script:step)/$($script:steps): $name" -PercentComplete $pct
    Write-Host ""
    Write-Host ("=== [{0}/{1}] {2} ===" -f $script:step, $script:steps, $name)
}

Write-Host ("[log] {0}  Windows {1}  PowerShell {2}  user {3}" -f (Get-Date -Format s), [Environment]::OSVersion.Version, $PSVersionTable.PSVersion, $env:USERNAME)
Write-Host "[log] arch: $env:PROCESSOR_ARCHITECTURE / $env:PROCESSOR_ARCHITEW6432   64-bit OS: $([Environment]::Is64BitOperatingSystem)"
Write-Host "[log] folder: $root  (src\texts.py present: $(Test-Path "$root\src\texts.py"), text\ present: $(Test-Path "$root\text"))"

# ---- environment checks
if (-not [Environment]::Is64BitOperatingSystem) { Fail "This game needs 64-bit Windows (raylib has no 32-bit build)." }
if (-not (Test-Path "$root\src\main.py") -or -not (Test-Path "$root\src\texts.py") -or -not (Test-Path "$root\text")) {
    Fail "The game folder is incomplete (src\main.py, src\texts.py or the text\ folder is missing). Copy or download the whole folder again."
}
try { New-Item -ItemType Directory -Force -Path $rt | Out-Null; Set-Content -Path "$rt\write.test" -Value 1 -ErrorAction Stop; Remove-Item "$rt\write.test" }
catch { Fail "Cannot write to $root. Move the game to a normal folder such as C:\Games\Skopje242 (not Program Files, not a read-only or zip-preview folder)." }
if ($root -match '\\(Temp|Rar\$[^\\]*)(\\|$)' -or $root -match '\.zip') { Say "WARNING: the game seems to run from a temporary / zip folder; extract it fully first." }
if ($root -match '[^\x00-\x7F]') { Say "Note: the folder path contains non-ASCII characters; if anything fails, move the game to e.g. C:\Games\Skopje242." }
# files from a downloaded zip are 'blocked' by Windows; unblock so nothing is silently refused
try { Get-ChildItem -Path $root -Recurse -File -Include *.py,*.ps1,*.bat,*.txt,*.json -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue } catch {}
# network: TLS 1.2, system proxy with the signed-in user's credentials
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}
try { [Net.WebRequest]::DefaultWebProxy.Credentials = [Net.CredentialCache]::DefaultNetworkCredentials } catch {}
$ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest is many times faster without its progress bar

# download with retries; falls back to curl.exe (built into Windows 10 1803+)
function Get-File($url, $out) {
    for ($i = 1; $i -le 3; $i++) {
        try { Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $out -ErrorAction Stop; if ((Test-Path $out) -and (Get-Item $out).Length -gt 0) { return $true } }
        catch { Say "download attempt $i failed: $($_.Exception.Message)" }
        if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
            & curl.exe -L --fail --silent --show-error -o $out $url 2>&1 | Out-Host
            if ($LASTEXITCODE -eq 0 -and (Test-Path $out) -and (Get-Item $out).Length -gt 0) { return $true }
        }
        Start-Sleep -Seconds (2 * $i)
    }
    return $false
}
function Expand-Zip($zip, $dest) {
    try { Expand-Archive -Force -Path $zip -DestinationPath $dest -ErrorAction Stop }
    catch {
        Say "Expand-Archive failed ($($_.Exception.Message)), using .NET"
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [IO.Compression.ZipFile]::ExtractToDirectory($zip, $dest)
    }
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
# a private python is usable only if it runs here (a venv copied from another PC points at a missing base Python) and has pip
function Test-Private($exe) {
    if (-not (Test-Path $exe)) { return $false }
    & $exe -c "import sys, pip" 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

$py = $null
if (Test-Private "$rt\venv\Scripts\python.exe") { $py = "$rt\venv\Scripts\python.exe" }
elseif (Test-Private "$rt\python\python.exe") { $py = "$rt\python\python.exe" }
else {
    foreach ($d in @("$rt\venv", "$rt\python")) {
        if (Test-Path $d) { Say "Removing unusable $d (copied from another PC or damaged) ..."; Remove-Item -Recurse -Force $d -ErrorAction SilentlyContinue }
    }
    $sys = $null
    foreach ($c in @(@{e='py'; a=@('-3.12')}, @{e='py'; a=@('-3.13')}, @{e='py'; a=@('-3.11')}, @{e='py'; a=@('-3.10')}, @{e='py'; a=@('-3')}, @{e='python'; a=@()}, @{e='python3'; a=@()})) {
        if (-not (Get-Command $c.e -ErrorAction SilentlyContinue)) { continue }
        $sys = Test-Python $c.e $c.a
        if ($sys) { break }
    }
    if ($sys) {
        Say "Using system Python: $sys"
        & $sys -m venv "$rt\venv" 2>&1 | Out-Host
        if ($LASTEXITCODE -eq 0 -and (Test-Private "$rt\venv\Scripts\python.exe")) { $py = "$rt\venv\Scripts\python.exe" }
        else { Say "venv creation failed or has no pip, falling back to a private Python"; Remove-Item -Recurse -Force "$rt\venv" -ErrorAction SilentlyContinue }
    } else { Say "No usable system Python (3.9-3.13, 64-bit) found - this is normal on a fresh Windows." }
    if (-not $py) {
        Say "Downloading a private Python 3.12 (about 10 MB) ..."
        $zip = "$rt\python-embed.zip"
        if (-not (Get-File 'https://www.python.org/ftp/python/3.12.8/python-3.12.8-embed-amd64.zip' $zip)) { Fail "Could not download Python (check your internet connection, proxy or firewall for python.org) and run run.bat again." }
        Expand-Zip $zip "$rt\python"
        $pth = Get-ChildItem "$rt\python" -Filter 'python*._pth' | Select-Object -First 1
        (Get-Content $pth.FullName) -replace '^#import site', 'import site' | Set-Content $pth.FullName
        if (-not (Get-File 'https://bootstrap.pypa.io/get-pip.py' "$rt\get-pip.py")) { Fail "Could not download pip (bootstrap.pypa.io)." }
        & "$rt\python\python.exe" "$rt\get-pip.py" --no-warn-script-location 2>&1 | Out-Host
        if ($LASTEXITCODE -ne 0) { Fail "pip installation failed." }
        $py = "$rt\python\python.exe"
    }
}
# embedded Python ignores the script folder (isolated ._pth mode): put src\ on its path for every script, old installs too
$pth = Get-ChildItem "$rt\python" -Filter 'python*._pth' -ErrorAction SilentlyContinue | Select-Object -First 1
if ($pth -and -not (Select-String -Path $pth.FullName -Pattern '^\.\.\\\.\.\\src$' -Quiet)) { Set-Content -Path $pth.FullName -Value (@(Get-Content $pth.FullName) + '..\..\src'); Say "added src to $($pth.Name)" }
Write-Host "[log] python: $py"

# ---------------------------------------------------------------- libraries
Step 'Libraries'
$libTest = "import pyray, numpy, PIL, mapbox_earcut"
function Pip-Install($pipArgs) {
    # 1) normal  2) upgrade pip + prefer wheels  3) trust the PyPI hosts (TLS-inspecting proxies)  -> each only if the previous failed
    & $py -m pip install --disable-pip-version-check --no-warn-script-location @pipArgs 2>&1 | Out-Host
    if ($LASTEXITCODE -eq 0) { return $true }
    Say "pip install failed - retrying (upgrading pip, wheels only) ..."
    & $py -m pip install --upgrade pip 2>&1 | Out-Null
    & $py -m pip install --disable-pip-version-check --no-warn-script-location --prefer-binary @pipArgs 2>&1 | Out-Host
    if ($LASTEXITCODE -eq 0) { return $true }
    Say "pip install failed - retrying with trusted PyPI hosts ..."
    & $py -m pip install --disable-pip-version-check --no-warn-script-location --prefer-binary --trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host pypi.python.org @pipArgs 2>&1 | Out-Host
    return ($LASTEXITCODE -eq 0)
}
$libErr = & $py -c $libTest 2>&1 | Out-String
if ($LASTEXITCODE -ne 0) {
    Say "Installing libraries (raylib, numpy, pillow, mapbox-earcut) ..."
    if (-not (Pip-Install @('-r', "$root\requirements.txt"))) { Fail "pip install failed three times. Check your internet connection / proxy / antivirus and run run.bat again." }
    $libErr = & $py -c $libTest 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0 -and $libErr -match 'DLL load failed|VCRUNTIME|MSVCP') {
        # numpy / raylib need the Visual C++ runtime, absent on a fresh Windows
        Say "A Windows runtime DLL is missing - installing the Microsoft Visual C++ Redistributable ..."
        $vc = "$rt\vc_redist.x64.exe"
        if (Get-File 'https://aka.ms/vs/17/release/vc_redist.x64.exe' $vc) {
            Start-Process $vc -ArgumentList '/install /quiet /norestart' -Wait -Verb RunAs
            $libErr = & $py -c $libTest 2>&1 | Out-String
        } else { Say "Could not download the VC++ runtime; install it from https://aka.ms/vs/17/release/vc_redist.x64.exe" }
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Host $libErr
        Fail "The libraries installed but do not import (see above). If it says 'DLL load failed', install https://aka.ms/vs/17/release/vc_redist.x64.exe and run run.bat again; otherwise delete the .runtime folder and retry."
    }
}
& $py -c "import osmium" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Say "Installing pyosmium (reads the Geofabrik map file; optional - Overpass is used without it) ..."
    & $py -m pip install --disable-pip-version-check --no-warn-script-location --prefer-binary osmium 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) { Say "pyosmium could not be installed - the map will come from Overpass." }
}
# the Macedonian voice: Suze for RHVoice, through Windows speech (SAPI); a failure never blocks the game
Step 'Voice (Suze, RHVoice)'
& $py -c "import comtypes" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { & $py -m pip install --disable-pip-version-check --no-warn-script-location comtypes 2>&1 | Out-Host }
$vo = & $py "$root\src\speech.py" 2>&1 | Out-String
Write-Host "[log] voice check (exit $LASTEXITCODE): $vo"
if ($LASTEXITCODE -ne 0 -and (Test-Path "$root\tools\rhvoice_urls.txt")) {
    Say "Installing the Macedonian voice Suze (RHVoice engine + voice, Windows may ask for permission) ..."
    $dl = "$rt\rhvoice"; New-Item -ItemType Directory -Force -Path $dl | Out-Null
    foreach ($u in (Get-Content "$root\tools\rhvoice_urls.txt" | Where-Object { $_ -match '^https://' })) {
        $f = Join-Path $dl ([IO.Path]::GetFileName(([Uri]$u).AbsolutePath))
        if (-not (Test-Path $f)) {
            try { Invoke-WebRequest -UseBasicParsing -Uri $u -OutFile "$f.part"; Move-Item -Force "$f.part" $f }
            catch { Say "Could not download $u"; continue }
        }
        try {
            if ($f -like '*.msi') { Start-Process msiexec.exe -ArgumentList "/i `"$f`" /qn /norestart" -Wait -Verb RunAs }
            else { Start-Process $f -ArgumentList '/S' -Wait -Verb RunAs }
        } catch { Say "Voice installer was cancelled or blocked ($($_.Exception.Message)) - the built-in voice is used." }
    }
    & $py "$root\src\speech.py"
    if ($LASTEXITCODE -ne 0) { Say "Suze is not available - the built-in voice is used. Run run.bat again to retry." }
}
Set-Content -Path "$rt\python.txt" -Value $py -Encoding ASCII

# final self-check, so the log proves the game's own imports work with this exact Python
Step 'Self-check'
Write-Host "[log] python: $py"
& $py -c "import sys; print(sys.version); print(sys.path)" 2>&1 | Out-Host
& $py -m pip list --disable-pip-version-check 2>&1 | Out-Host
$chk = & $py -c "import sys; sys.path.insert(0, r'$root\src'); from texts import TXT; import pyray, numpy, PIL, mapbox_earcut; print('imports OK')" 2>&1 | Out-String
Write-Host "[log] self-check (exit $LASTEXITCODE): $chk"
if ($LASTEXITCODE -ne 0) { Fail "Final check failed: the game cannot import its modules with this Python (see above). Delete the .runtime folder and run run.bat again." }
try { Stop-Transcript | Out-Null } catch {}

try { Copy-Item "$root\requirements.txt" "$root\.runtime\stamp_req.txt" -Force; Copy-Item "$root\tools\setup.ps1" "$root\.runtime\stamp_setup.ps1" -Force } catch {}   # run.bat skips setup while these match
Write-Progress -Activity "Skopje 242 setup" -Completed
Say "Ready - starting the game (the map is downloaded and built inside the game window, with a progress screen)."
exit 0
