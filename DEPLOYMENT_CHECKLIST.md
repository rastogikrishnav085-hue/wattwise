# WattWise v2 — Deployment Checklist

## Local
- [x] Python compile check
- [x] 151 automated tests passing
- [x] Supabase PostgreSQL connection
- [x] Streamlit dashboard launch
- [x] Forecast run persistence
- [x] WhattsOn deterministic fallback
- [x] Gemini integration with fallback

## GitHub
1. Create an empty GitHub repository named `wattwise`.
2. Do not add README, .gitignore, or license during repository creation.
3. From the project folder run `push_to_github.bat`.
4. Confirm `.env`, secrets, local databases, CSV/TXT data, `.venv`, and caches are not tracked.
5. Confirm `models/*.pkl` and `models/*.json` remain tracked because the release expects the model artifacts.

## Streamlit Community Cloud — dashboard
- Repository: GitHub `wattwise`
- Branch: `main`
- Main file: `app.py`
- Python: 3.12
- Secret: `DATABASE_URL`
- Optional secrets: `GEMINI_API_KEY`, `WATTWISE_USE_GEMINI`, `GEMINI_MODEL`

## Render — API (recommended)
- Blueprint: `render.yaml`
- `DATABASE_URL`: Supabase Session pooler
- `GEMINI_API_KEY`: secret
- `WATTWISE_USE_GEMINI=true`
- `GEMINI_MODEL=gemini-3.8-flash`
- Test `/health` and `/docs`

## Vercel — API (optional)
- Uses `api/index.py` and `vercel.json`
- Set the same production environment variables as Render
- Test `/health` and `/docs`
- Do not attempt to deploy the Streamlit `app.py` as the Vercel frontend

## Supabase
- Keep database password and connection string private.
- Use the Session pooler connection for broad IPv4 compatibility.
- Do not commit `.env` or any secrets.

## Before SIH demo
1. Run `verify_wattwise.bat` locally.
2. Open the deployed dashboard.
3. Run a fresh forecast.
4. Test WhattsOn with:
   - `What is my forecast for tomorrow?`
   - `Will I exceed my sanctioned load?`
   - `How much can I save by shifting production?`
   - `Do I have any anomalies?`
   - `What is the model accuracy?`
5. Rotate any API key that has ever been exposed in logs/screenshots.
6. Open the app 5–10 minutes before presenting so sleeping free-tier services are awake.
