@echo off
call "%~dp0_common.bat" || exit /b 1
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0setup_app.py"
