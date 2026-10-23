@echo off
REM ============================================================
REM  Skopje 242 - one-click start.  Double-click this file.
REM  First run: sets up Python + libraries, downloads the OSM map
REM  data for Skopje and builds the world (a few minutes).
REM  Later runs start the game straight away.
REM    run.bat            normal start
REM    run.bat demo       use the offline synthetic demo city
REM    run.bat refresh    re-download the map data and rebuild
REM    run.bat aivoice    one-time install of the optional neural voice
REM    run.bat windowed   (any other args go to the game, e.g. --size 1280x720)
REM ============================================================
setlocal
cd /d "%~dp0"
title Skopje 242

set GAMEARGS=
if /I "%~1"=="demo" (set GAMEARGS=--demo& shift)
if /I "%~1"=="refresh" (set GAMEARGS=--refresh& shift)
set SETUP_ARGS=
if /I "%~1"=="aivoice" (set SETUP_ARGS=-AiVoice& shift)

powershell -NoProfile -ExecutionPolicy Bypass -File "tools\setup.ps1" %SETUP_ARGS%
if errorlevel 1 (
    echo.
    echo Setup failed - see the messages above.
    pause
    exit /b 1
)

set /p PY=<".runtime\python.txt"
"%PY%" "src\main.py" %GAMEARGS% %1 %2 %3 %4 %5 %6 %7 %8 %9
if errorlevel 1 (
    echo.
    echo The game exited with an error.
    pause
)
endlocal
