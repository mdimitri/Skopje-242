@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
set "setup_exit=%ERRORLEVEL%"
if not "%setup_exit%"=="0" (
  echo.
  echo Setup failed. The model file was not installed.
  pause
)
exit /b %setup_exit%
