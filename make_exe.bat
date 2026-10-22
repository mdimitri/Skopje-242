@echo off
REM Optional: bundle the game into dist\SkopjeGTA\SkopjeGTA.exe (PyInstaller). Run run.bat once first.
REM NOTE: experimental - not verified in the cloud build environment.
setlocal
cd /d "%~dp0"
set /p PY=<".runtime\python.txt"
set /p WORLD=<".runtime\world.txt"
"%PY%" -m pip install --disable-pip-version-check pyinstaller || exit /b 1
"%PY%" -m PyInstaller --noconfirm --onedir --name SkopjeGTA --paths src --collect-all pyray --collect-all raylib src\main.py || exit /b 1
mkdir dist\SkopjeGTA\data\cache 2>nul
xcopy /E /I /Y "%WORLD%" dist\SkopjeGTA\data\cache\world >nul
echo @echo off> dist\SkopjeGTA\play.bat
echo "%%~dp0SkopjeGTA.exe" --world "%%~dp0data\cache\world">> dist\SkopjeGTA\play.bat
echo Done: dist\SkopjeGTA\play.bat
