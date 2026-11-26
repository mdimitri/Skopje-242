@echo off
cd /d "%~dp0"
if not exist "node_modules\sharp\package.json" (
  echo Run setup.bat first to install the required packages.
  pause
  exit /b 1
)
node server.js
