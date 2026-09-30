#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo "============================================"
echo "  WattWise v2 - SIH 2026"
echo "  One-time setup + launch"
echo "============================================"
echo ""

if ! command -v python3 &> /dev/null; then
    echo "[ERROR] python3 was not found on this machine."
    echo "Install Python 3.11+ from https://www.python.org/downloads/"
    exit 1
fi
echo "[OK] Found $(python3 --version)"
echo ""

if [ ! -d ".venv" ]; then
    echo "[SETUP] Creating virtual environment (.venv)..."
    python3 -m venv .venv
    echo "[OK] Virtual environment created."
else
    echo "[OK] Virtual environment already exists."
fi
echo ""

source .venv/bin/activate

echo "[SETUP] Installing dependencies from requirements.txt..."
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
echo "[OK] Dependencies installed."
echo ""

export WATTWISE_ENV="${WATTWISE_ENV:-development}"

if [ -f "data/household_power_consumption.txt" ]; then
    echo "[DATA] Real dataset found in data/ - the app will use it."
else
    echo "[DATA] No real dataset found - running in DEMO MODE with"
    echo "       synthetic MSME-shaped data. See README.md, section"
    echo "       'Where to add your own data and API keys', to plug in"
    echo "       a real dataset."
fi
echo ""

echo "[SETUP] Running first-time database setup..."
python scripts/bootstrap.py
echo ""

echo "[CHECK] Running test suite..."
python -m pytest tests/ -q || true
echo ""

echo "[LAUNCH] Starting WattWise API in the background (http://localhost:8000)..."
uvicorn api:app --host 127.0.0.1 --port 8000 > api.log 2>&1 &
API_PID=$!
trap "kill $API_PID 2>/dev/null" EXIT
sleep 2

echo "[LAUNCH] Starting WattWise dashboard..."
echo "         Dashboard: http://localhost:8501"
echo "         API docs:  http://localhost:8000/docs"
echo ""
echo "         Log in on the dashboard with the API key printed above,"
echo "         or use the 'New company - sign up' tab to create your own."
echo ""
echo "         Press CTRL+C in this terminal to stop everything."
echo "============================================"
echo ""

streamlit run app.py
