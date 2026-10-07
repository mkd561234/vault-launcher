@echo off
rem Vault Launcher. Downloads a private copy of Python the first time
rem (from python.org, checked against its published SHA-256), then runs the launcher with it.
setlocal EnableExtensions
set "KDIR=%LOCALAPPDATA%\VaultLauncher"
set "PYDIR=%KDIR%\python"
set "PYZIP=python-3.14.4-embeddable-win32.zip"
set "PYURL=https://www.python.org/ftp/python/3.14.4/%PYZIP%"
set "PYSHA=41dcffdbc95dcc71593b24e8e4f973d75bfa63aef09d9b2c833a247ddeb825e4"
if exist "%PYDIR%\python.exe" goto run
if not exist "%KDIR%" mkdir "%KDIR%"
if not exist "%PYDIR%" mkdir "%PYDIR%"
rem The older Krieg Launcher already downloaded the same Python: reuse it.
if exist "%LOCALAPPDATA%\KriegTPS\python\python.exe" xcopy /e /i /q /y "%LOCALAPPDATA%\KriegTPS\python" "%PYDIR%" >nul
if exist "%PYDIR%\python.exe" goto run
echo Downloading a private copy of Python from python.org (about 10 MB, one time only)...
curl.exe -L --fail --silent --show-error -o "%KDIR%\%PYZIP%" "%PYURL%"
if errorlevel 1 powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -UseBasicParsing -Uri '%PYURL%' -OutFile '%KDIR%\%PYZIP%'"
if not exist "%KDIR%\%PYZIP%" goto dlfail
set "GOT="
for /f "delims=" %%h in ('certutil -hashfile "%KDIR%\%PYZIP%" SHA256 ^| findstr /v ":"') do if not defined GOT set "GOT=%%h"
set "GOT=%GOT: =%"
if /i not "%GOT%"=="%PYSHA%" goto hashfail
tar -xf "%KDIR%\%PYZIP%" -C "%PYDIR%"
if errorlevel 1 powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Force -Path '%KDIR%\%PYZIP%' -DestinationPath '%PYDIR%'"
del "%KDIR%\%PYZIP%" >nul 2>&1
if not exist "%PYDIR%\python.exe" goto dlfail
:run
if /i "%~1"=="launcher" (
  start "" "%PYDIR%\pythonw.exe" "%~dp0run.py" launcher
  exit /b 0
)
"%PYDIR%\python.exe" "%~dp0run.py" %*
exit /b %errorlevel%
:dlfail
echo.
echo Could not download Python from python.org. Check your internet connection and try again.
exit /b 1
:hashfail
del "%KDIR%\%PYZIP%" >nul 2>&1
echo.
echo The Python download did not match its official checksum, so it was deleted. Please try again.
exit /b 1
