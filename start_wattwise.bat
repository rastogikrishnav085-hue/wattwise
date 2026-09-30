@echo off
setlocal enabledelayedexpansion
title WattWise v2 - SIH 2026
cd /d "%~dp0"

echo ============================================
echo   WattWise v2 - SIH 2026
echo   One-time setup + launch
echo ============================================
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python was not found on this machine.
    echo Install Python 3.11+ from https://www.python.org/downloads/
    echo IMPORTANT: during install, tick "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo [OK] Found Python %PYVER%
echo.

if not exist ".venv\" (
    echo [SETUP] Creating virtual environment: .venv
    python -m venv .venv
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created.
) else (
    echo [OK] Virtual environment already exists.
)
echo.

call ".venv\Scripts\activate.bat"
if %errorlevel% neq 0 (
    echo [ERROR] Failed to activate virtual environment.
    pause
    exit /b 1
)

echo [SETUP] Installing dependencies from requirements.txt...
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo [ERROR] Dependency installation failed. Check your internet connection.
    pause
    exit /b 1
)
echo [OK] Dependencies installed.
echo.

if not defined WATTWISE_ENV set WATTWISE_ENV=development

if exist "data\household_power_consumption.txt" (
    echo [DATA] Real dataset found in data\ - the app will use it.
) else (
    echo [DATA] No real dataset found - running in DEMO MODE with
    echo        synthetic MSME-shaped data. See README.md, section
    echo        "Where to add your own data and API keys", to plug in
    echo        a real dataset.
)
echo.

echo [SETUP] Running first-time database setup...
python scripts\bootstrap.py
echo.

echo [CHECK] Running test suite...
python -m pytest tests\ -q
if !errorlevel! neq 0 (
    echo.
    echo [ERROR] Tests failed. WattWise will NOT be launched.
    pause
    exit /b 1
)
echo [OK] Test suite passed.
echo.

echo [LAUNCH] Starting WattWise API in the background (http://localhost:8000)...
start /min "WattWise API" cmd /c "call .venv\Scripts\activate.bat && uvicorn api:app --host 127.0.0.1 --port 8000"
timeout /t 3 /nobreak >nul

echo [LAUNCH] Starting WattWise dashboard...
echo          Dashboard: http://localhost:8501
echo          API docs:  http://localhost:8000/docs
echo.
echo          Log in on the dashboard with the API key printed above,
echo          or use the "New company - sign up" tab to create your own.
echo.
echo          Press CTRL+C in this window to stop the dashboard.
echo          (The API window can be closed separately from the taskbar.)
echo ============================================
echo.

streamlit run app.py

echo.
echo Dashboard stopped. The API may still be running in its own window.
echo Press any key to close this window.
pause >nul
