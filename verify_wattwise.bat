@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] .venv not found. Run start_wattwise.bat first.
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"
echo [1/3] Python compile check...
python -m compileall -q app.py api.py predict.py scripts src || exit /b 1
echo [2/3] Test suite...
python -m pytest tests\ -q || exit /b 1
echo [3/3] Database check...
python scripts\check_database.py || exit /b 1
echo.
echo [OK] WattWise local verification passed.
pause
