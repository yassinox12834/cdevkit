@echo off
rem Shared by setup.bat and launcher.bat. No .exe is built, so Windows SmartScreen never
rem shows its "unrecognised app" warning.
rem  1. If Python 3.10+ is installed, it is used.
rem  2. Otherwise a private Python is downloaded into the .runtime folder with uv
rem     (https://github.com/astral-sh/uv). Nothing is installed on the system:
rem     delete this folder and everything is gone.
rem Set CDEVKIT_PORTABLE=1 to always use the private Python.
setlocal
cd /d "%~dp0"

rem ---- Already set up? -------------------------------------------------------
rem .deps-ok holds a copy of requirements.txt, so an update of the app rebuilds the environment.
if not exist ".venv\.deps-ok" goto choose
fc /b requirements.txt ".venv\.deps-ok" >nul 2>nul || goto rebuild
".venv\Scripts\python.exe" -c "import PySide6" >nul 2>nul && exit /b 0
:rebuild
echo Setting up the environment again (the app was updated, or the folder was moved)...
rmdir /s /q ".venv"

:choose
if exist ".venv" rmdir /s /q ".venv"
set "PY="
if "%CDEVKIT_PORTABLE%"=="1" goto portable
py -3 -c "import sys,venv;sys.exit(sys.version_info<(3,10))" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys,venv;sys.exit(sys.version_info<(3,10))" >nul 2>nul && set "PY=python"
if not defined PY goto portable

rem ---- Installed Python ------------------------------------------------------
echo Using your installed Python. Creating the environment, this takes a minute or two...
%PY% -m venv .venv || goto venv_failed
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto pip_failed
goto done

rem ---- Private Python, kept inside this folder ----------------------------------
:portable
set "RT=%~dp0.runtime"
set "UV=%RT%\uv.exe"
set "UV_PYTHON_INSTALL_DIR=%RT%\python"
set "UV_CACHE_DIR=%RT%\cache"
set "UV_PYTHON_PREFERENCE=only-managed"
if exist "%UV%" goto have_uv
echo No suitable Python found. Downloading a private copy into the .runtime folder.
echo This happens once and takes about 60 MB.
rem uv is pinned to one release and checked against its published SHA-256,
rem so a changed or tampered download is refused instead of run.
set "UV_VERSION=0.13.9"
set "ARCH=x86_64"
set "UV_SHA=edd61f7f5728a56cc62455386661860bdfc7bab65872f39b0c25bdcc1d8e1beb"
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "ARCH=aarch64"
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "UV_SHA=72eed595983a4d7d22d79f21065b0f4479cc7e5c7a89104bb410c8f47559a878"
if not exist "%RT%" mkdir "%RT%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $z=Join-Path $env:TEMP 'cdevkit-uv.zip'; Invoke-WebRequest -UseBasicParsing -Uri ('https://github.com/astral-sh/uv/releases/download/' + $env:UV_VERSION + '/uv-' + $env:ARCH + '-pc-windows-msvc.zip') -OutFile $z; if ((Get-FileHash -Algorithm SHA256 $z).Hash -ne $env:UV_SHA) { Remove-Item $z; Write-Host 'The downloaded uv does not match its expected checksum, so it was not used.'; exit 1 }; Expand-Archive -Force -Path $z -DestinationPath $env:RT; Remove-Item $z"
if not exist "%UV%" goto download_failed

:have_uv
echo Preparing Python 3.12...
"%UV%" venv ".venv" --python 3.12 --quiet || goto download_failed
"%UV%" pip install --python ".venv\Scripts\python.exe" --quiet -r requirements.txt || goto pip_failed
goto done

rem ---- Results ---------------------------------------------------------------
:done
copy /y requirements.txt ".venv\.deps-ok" >nul
exit /b 0

:venv_failed
echo Could not create the environment with your Python. Trying the private Python instead...
if exist ".venv" rmdir /s /q ".venv"
goto portable

:download_failed
echo.
echo Could not download Python. Check your internet connection and run this file again,
echo or install Python yourself from https://www.python.org/downloads/
echo You can also install everything without the app: see docs\install\WINDOWS.md
pause
exit /b 1

:pip_failed
echo.
echo Could not install the Qt interface. Check your internet connection and run this file again.
pause
exit /b 1
