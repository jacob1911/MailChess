@echo off
REM ============================================================
REM MailChess Startup Script (Windows) - AUTOMATED SETUP
REM ============================================================
echo ============================================================
echo         MailChess - Project Setup
echo ============================================================
echo.
REM Change to script directory
cd /d "%~dp0"
REM ------------------------------------------------------------
REM 1. POLICY BYPASS (Crucial for VENV activation)
REM ------------------------------------------------------------
echo [1/5] Configuring Execution Policy for this session...
powershell -Command "Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process -Force"
if %errorlevel% neq 0 (
echo [WARNING] Could not set execution policy. Setup might fail if scripts are blocked.
) else (
echo [OK] Execution policy configured.
)
echo.
REM ------------------------------------------------------------
REM 2. PYTHON CHECK
REM ------------------------------------------------------------
echo [2/5] Checking Python installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
echo [ERROR] Python is not installed!
pause
exit /b 1
)
python --version
echo [OK] Python is installed
echo.
REM ------------------------------------------------------------
REM 3. VIRTUAL ENVIRONMENT SETUP
REM ------------------------------------------------------------
echo [3/5] Setting up Virtual Environment...
REM If the folder exists but is broken, remove it first
if exist ".venv" (
".venv\Scripts\python.exe" --version >nul 2>&1
if %errorlevel% neq 0 (
echo [INFO] Repairing broken virtual environment...
rd /s /q ".venv"
)
)
if not exist ".venv\Scripts\activate.bat" (
echo Creating virtual environment...
python -m venv .venv
)
REM Activate VENV
echo Activating virtual environment...
call .venv\Scripts\activate.bat
REM Check and install requirements
echo Checking and installing dependencies...
pip install -r requirements.txt --upgrade
if %errorlevel% neq 0 (
echo [ERROR] Failed to install dependencies
pause
exit /b 1
)
echo [OK] All dependencies installed
echo.
REM Run environment setup (generates environ.env with Flask secret key)
echo [4/5] Setting up environment configuration...
python setup_env.py
if %errorlevel% neq 0 (
echo [ERROR] Environment setup failed
pause
exit /b 1
)
REM Create directories
if not exist "instance" (
echo Creating instance directory for database...
mkdir instance
)
if not exist "static\label_icons" (
echo Creating label_icons directory...
mkdir static\label_icons
)
REM Deactivate VENV after setup is complete
deactivate
echo.
echo ============================================================
echo Setup Complete!
echo Run desktop.bat to launch the application.
echo ============================================================
pause
