@echo off
REM MailChess Launcher
REM This script automatically uses the virtual environment

REM 1. Change directory to where this script is located
cd /d "%~dp0"

REM 2. Run desktop_main.py using the VENV python executable directly
REM This avoids needing to run "activate" scripts
".venv\Scripts\python.exe" desktop_main.py

REM 3. Keep window open only if there was an error
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] The application crashed!
    pause
)
