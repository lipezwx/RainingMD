@echo off
setlocal
cd /d "%~dp0"
rem ---------------------------------------------------------------
rem  Raining Md - one-click build
rem    1. the app            -> dist\RainingMd\
rem    2. the payload zip    -> payload\payload.zip
rem    3. the installer      -> dist_installer\rainingmd-installer.exe
rem  Needs 64-bit Python 3.13. To use another version:  set PYTHON_SPEC=-3.14-64
rem ---------------------------------------------------------------
if "%PYTHON_SPEC%"=="" set PYTHON_SPEC=-3.13-64

py %PYTHON_SPEC% --version >nul 2>&1
if errorlevel 1 goto nopython

if not exist .venv\Scripts\python.exe py %PYTHON_SPEC% -m venv .venv
if errorlevel 1 goto fail
call .venv\Scripts\activate.bat

python -m pip install --upgrade pip
python -m pip install -r requirements-build.txt
if errorlevel 1 goto fail

if exist build rmdir /s /q build
if exist build_installer rmdir /s /q build_installer
if exist dist rmdir /s /q dist
if exist dist_installer rmdir /s /q dist_installer
if exist payload rmdir /s /q payload

echo.
echo === 1/3  Building the app ===
pyinstaller --noconfirm --clean --windowed --name RainingMd ^
  --icon assets\icon.ico --add-data "assets;assets" ^
  --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick --exclude-module PySide6.QtWebEngineCore ^
  --exclude-module PySide6.Qt3DCore --exclude-module PySide6.QtMultimedia --exclude-module tkinter ^
  main.py
if errorlevel 1 goto fail

echo.
echo === 2/3  Packing the payload ===
python make_payload.py
if errorlevel 1 goto fail

echo.
echo === 3/3  Building rainingmd-installer.exe ===
pyinstaller --noconfirm --clean --onefile --windowed --name rainingmd-installer ^
  --icon assets\icon.ico --distpath dist_installer --workpath build_installer ^
  --add-data "assets\logo.png;assets" --add-data "assets\icon.png;assets" --add-data "payload\payload.zip;assets" ^
  --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick --exclude-module PySide6.QtWebEngineCore ^
  --exclude-module PySide6.Qt3DCore --exclude-module PySide6.QtMultimedia --exclude-module tkinter ^
  installer.py
if errorlevel 1 goto fail

echo.
echo Done. Installer: %~dp0dist_installer\rainingmd-installer.exe
exit /b 0

:nopython
echo Python %PYTHON_SPEC% was not found. Install 64-bit Python 3.13 from python.org, or set PYTHON_SPEC.
exit /b 1

:fail
echo Build failed.
exit /b 1
