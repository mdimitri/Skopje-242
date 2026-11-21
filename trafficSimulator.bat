@echo off
REM ============================================================
REM  Skopje 242 - Traffic Lab.  Double-click this file.
REM  The game's own traffic (cars, buses, emergency vehicles, trains,
REM  pedestrians, traffic lights) on a full-screen 2D map: change the
REM  rules live, edit roads and junctions, run seeded batches and
REM  explore new rules on all cores, read the efficiency / safety /
REM  speed report, and apply the winning settings to the real game.
REM    trafficSimulator.bat                 full screen
REM    trafficSimulator.bat --windowed      in a window
REM    trafficSimulator.bat --batch spec.json   / --explore spec.json   headless
REM  Needs the game set up once (run.bat): Python + the built world.
REM ============================================================
setlocal
cd /d "%~dp0"
title Skopje 242 - Traffic Lab
if not exist ".runtime\python.txt" (
    echo Start the game once with run.bat first: it installs Python and the libraries.
    pause
    exit /b 1
)
set /p PY=<".runtime\python.txt"
if not exist "%PY%" (
    echo The Python recorded by setup was not found: %PY%  - run run.bat once.
    pause
    exit /b 1
)
REM One-time: "Skopje 242 Traffic Lab" shortcut with the game icon here and on the desktop (delete it to have it made again)
set "PSH=%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PSH%" set "PSH=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PSH%" set "PSH=powershell"
if not exist "Skopje 242 Traffic Lab.lnk" "%PSH%" -NoProfile -ExecutionPolicy Bypass -File "tools\shortcut.ps1" -Name "Skopje 242 Traffic Lab" -Bat "trafficSimulator.bat" -Style 1 >nul 2>&1
if not exist "data\cache\world\manifest.json" (
    echo The world is not built yet: start the game once with run.bat so it builds data\cache\world.
    pause
    exit /b 1
)
"%PY%" "tools\traffic_lab.py" %*
if errorlevel 1 pause
endlocal
