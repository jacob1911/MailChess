@echo off
REM ============================================================
REM MailChess Startup Script (Windows)
REM ============================================================

echo ============================================================
echo         MailChess - Chess via Email
echo ============================================================
echo.

REM Change to script directory
cd /d "%~dp0"

REM Check if Python is installed
echo [1/5] Checking Python installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed!
    echo.
    echo Please download and install Python from:
    echo https://www.python.org/downloads/
    echo.
    echo Make sure to check "Add Python to PATH" during installation!
    pause
    exit /b 1
)

python --version
echo [OK] Python is installed
echo.



REM Check and install requirements
echo [4/5] Checking dependencies...
pip show Flask >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing dependencies from requirements.txt...
    pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to install dependencies
        pause
        exit /b 1
    )
    echo [OK] All dependencies installed
) else (
    echo [OK] Dependencies already installed
    echo Checking for updates...
    pip install -r requirements.txt --upgrade --quiet
)
echo.

REM Check if environ.env exists
if not exist "environ.env" (
    echo [WARNING] environ.env not found!
    echo Please create environ.env with required API keys:
    echo   - FLASK_SECRET_KEY
    echo   - GOOGLE_CLIENT_ID
    echo   - GOOGLE_CLIENT_SECRET
    echo   - OPENAI_API_KEY
    echo.
    pause
)

REM Check if instance directory exists
if not exist "instance\" (
    echo Creating instance directory for database...
    mkdir instance
)

REM Check if static/label_icons directory exists
if not exist "static\label_icons\" (
    echo Creating label_icons directory...
    mkdir static\label_icons
)

REM Start Flask application
echo [5/5] Starting MailChess application...
echo.
echo ============================================================
echo Server starting at http://127.0.0.1:5000
echo Press CTRL+C to stop the server
echo ============================================================
echo.

set FLASK_APP=app.py
set FLASK_ENV=development
python app.py

REM If Flask exits, pause so user can see error messages
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Application stopped with error code %errorlevel%
    pause
)
