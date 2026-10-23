@echo off
REM Optional: bundle the game into dist\Skopje242\Skopje242.exe (PyInstaller). Run run.bat once first.
REM NOTE: experimental - not verified in the cloud build environment.
setlocal
cd /d "%~dp0"
set /p PY=<".runtime\python.txt"
set /p WORLD=<".runtime\world.txt"
"%PY%" -m pip install --disable-pip-version-check pyinstaller || exit /b 1
"%PY%" -m PyInstaller --noconfirm --onedir --name Skopje242 --paths src --collect-all pyray --collect-all raylib src\main.py || exit /b 1
mkdir dist\Skopje242\data\cache 2>nul
xcopy /E /I /Y "%WORLD%" dist\Skopje242\data\cache\world >nul
echo @echo off> dist\Skopje242\play.bat
echo "%%~dp0Skopje242.exe" --world "%%~dp0data\cache\world">> dist\Skopje242\play.bat
echo Done: dist\Skopje242\play.bat
