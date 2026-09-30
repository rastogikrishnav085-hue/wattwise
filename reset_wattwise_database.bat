@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] .venv not found. Run start_wattwise.bat first.
  pause
  exit /b 1
)
echo.
echo ============================================
echo   WattWise - RESET DEMO DATABASE
echo ============================================
echo This will permanently remove all WattWise
 echo companies, users, forecasts, training runs,
echo recommendations, consultant notes and audit logs.
echo.
".venv\Scripts\python.exe" scripts\reset_demo_database.py
if errorlevel 1 (
  echo.
  echo [ERROR] Database reset failed.
  pause
  exit /b 1
)
echo.
echo [OK] Fresh demo company created.
pause
