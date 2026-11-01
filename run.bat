@echo off
REM ============================================================
REM  Skopje 242 - one-click start.  Double-click this file.
REM  First run: sets up Python + libraries, downloads the OSM map
REM  data for Skopje and builds the world (a few minutes).
REM  Later runs start the game straight away.
REM    run.bat            normal start
REM    run.bat demo       use the offline synthetic demo city
REM    run.bat setup      force the full setup check (normally skipped once it has succeeded)
REM    run.bat refresh    re-download the map data and rebuild
REM    run.bat aivoice    one-time install of the optional neural voice
REM    run.bat windowed   (any other args go to the game, e.g. --size 1280x720)
REM ============================================================
setlocal
cd /d "%~dp0"
title Skopje 242

REM Fast path: setup already finished for this requirements.txt / setup.ps1 -> skip it and start the game in a minimized console,
REM so the game's own loading screen is what you look at.  "run.bat setup" forces the full setup again.
set FASTOK=
if exist ".runtime\python.txt" if exist ".runtime\stamp_req.txt" if exist ".runtime\stamp_setup.ps1" (
    fc /b requirements.txt ".runtime\stamp_req.txt" >nul 2>&1 && fc /b tools\setup.ps1 ".runtime\stamp_setup.ps1" >nul 2>&1 && set FASTOK=1
)
if /I "%~1"=="setup" (set FASTOK=& shift)
if /I "%~1"=="aivoice" set FASTOK=
if defined FASTOK if not defined SK_MIN (
    set SK_MIN=1
    start "Skopje 242" /min cmd /c ""%~f0" %*"
    exit /b 0
)

set GAMEARGS=
if /I "%~1"=="demo" (set GAMEARGS=--demo& shift)
if /I "%~1"=="refresh" (set GAMEARGS=--refresh& shift)
set SETUP_ARGS=
if /I "%~1"=="aivoice" (set SETUP_ARGS=-AiVoice& shift)

if not exist "src\main.py" (
    echo The game folder is incomplete: src\main.py is missing. Copy or download the whole folder again.
    pause
    exit /b 1
)
if not exist "src\texts.py" (
    echo The game folder is incomplete: src\texts.py is missing. Copy or download the whole folder again.
    pause
    exit /b 1
)

REM 64-bit Windows PowerShell by its full path (PATH may be broken, or a 32-bit shell may be running)
set "PSH=%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PSH%" set "PSH=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PSH%" set "PSH=powershell"
if defined FASTOK goto :skipsetup
"%PSH%" -NoProfile -ExecutionPolicy Bypass -File "tools\setup.ps1" %SETUP_ARGS%
if errorlevel 1 (
    echo.
    echo Setup failed - see the messages above and logs\install.log
    pause
    exit /b 1
)

:skipsetup
if not exist ".runtime\python.txt" (
    echo Setup did not finish: .runtime\python.txt is missing. See logs\install.log
    pause
    exit /b 1
)
set /p PY=<".runtime\python.txt"
if not exist "%PY%" (
    echo The Python recorded by setup was not found: %PY%
    echo Delete the .runtime folder and run run.bat again.
    pause
    exit /b 1
)
"%PY%" "src\main.py" %GAMEARGS% %1 %2 %3 %4 %5 %6 %7 %8 %9
if errorlevel 1 (
    echo.
    echo The game exited with an error. See logs\crash.log and logs\install.log
    pause
)
endlocal
