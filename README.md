# WattWise v2 — MSME Energy Intelligence Platform

SIH 2026. Zero-hardware, ML-driven energy forecasting and peak-load
optimization for MSMEs — predicts sanctioned-load breaches hours ahead,
flags peak-tariff vs. peak-consumption independently, detects anomalies,
and includes a trend-aware consultant layer, a conversational WhattsOn
assistant, user-upload support, and multi-tenant, security-hardened deployment.

## Quick start (one-click)

**Mac/Linux:**
```
./start_wattwise.sh
```

**Windows:** double-click `start_wattwise.bat`

Either script will, in order: create a virtual environment, install
dependencies, initialize the database, create a demo company (printing
its API key — **save it, it is shown only once**), run the test suite,
then start the API at `http://localhost:8000` and the dashboard at
`http://localhost:8501`.

Log into the dashboard with the printed API key, or use the "New company
— sign up" tab to create your own company profile (tier, industry,
sanctioned load, shift pattern).

## Project layout

```
wattwise_v2/
├── api.py                  FastAPI service (multi-tenant, per-company auth)
├── app.py                  Streamlit dashboard
├── predict.py              standalone CLI inference (no server needed)
├── src/                    the actual pipeline — see each file's own docstring
│   ├── database.py         multi-tenant persistence (SQLite locally, Postgres/Supabase online)
│   ├── data_quality.py     rejects garbage datasets before they reach training
│   ├── security.py         per-company API key auth, rate limiting
│   ├── data_loader.py      real / uploaded / synthetic (incl. MSME-shaped) data
│   ├── features.py         shift-aware feature engineering
│   ├── forecast.py         ARIMA + Random Forest ensemble, CV, confidence intervals
│   ├── flags.py            peak-tariff flagging + anomaly detection
│   ├── demand_limit.py     sanctioned-load breach detection
│   ├── savings.py          cost/savings simulation
│   ├── recommendations.py  immediate (this-forecast) advisory rules
│   ├── consultant.py       trending + strategic advisory layer (new)
│   ├── report.py           Markdown report
│   ├── pdf_report.py       PDF report
│   └── external_apis.py    <-- placeholder for real third-party integrations, see below
├── tests/                  full pytest suite (149 tests), mirrors src/ 1:1
├── scripts/
│   ├── bootstrap.py        first-run DB + demo company setup
│   ├── check_database.py   tests your DATABASE_URL (Supabase) and explains any error in plain English
│   └── backup_db.sh        nightly SQLite backup (cron this)
├── nginx/wattwise.conf     TLS-terminating reverse proxy config
├── Dockerfile.api, Dockerfile.dashboard, docker-compose.yml   (self-hosting option)
├── render.yaml             Render blueprint for the free public API
├── .streamlit/             dashboard theme + secrets template
├── DEPLOYMENT.md           step-by-step: put it online for free
├── .github/workflows/ci.yml
└── .env.example
```

## Putting it online (free)

Follow **DEPLOYMENT.md**: Supabase (free Postgres) + Render (API) +
Streamlit Community Cloud (dashboard). No credit card, about 30 minutes.

Running locally needs none of that: with no `DATABASE_URL` set it uses a
SQLite file automatically.

## Running with Docker instead (self-hosting)

```
cp .env.example .env      # fill in real values
docker compose up --build
```

Nginx fronts both services on 443/80. Replace the placeholder cert paths in
`nginx/wattwise.conf` with a real certificate before going live.

## Multi-tenancy model

Every company gets its own row in `companies`, its own API key (hashed,
never stored in plaintext), and its own trained models under
`models/company_{id}/` (on free hosts these files don't survive a restart, which is
fine: every forecast retrains in seconds; all data lives in the database).
All database queries are scoped by `company_id`.

## WhattsOn conversational assistant

The dashboard includes a **WhattsOn** chat tab and the API exposes `POST /whatts-on`.
WhattsOn answers questions from the latest structured WattWise outputs, including
forecast cost drivers, sanctioned-load risk, estimated savings, anomalies, MAE/RMSE
model performance, recommendations, and consultant trends. It is deterministic and
provider-agnostic in the current version, so it requires no external LLM API key.
A future LLM can be placed behind the same interface without changing the UI/API contract.

WhattsOn is an explanation and decision-support layer, not an autonomous industrial
control agent; the MSME operator remains responsible for final actions.

## User-uploaded data

The uploader accepts `.csv` and `.txt` files up to 50 MB. It supports the canonical
UCI-style `Date;Time;Global_active_power` format and common MSME exports with a
`datetime`/`timestamp` column plus a consumption field such as `load_kw`, `power_kw`,
`demand_kw`, `consumption`, `power`, or `load`. Uploaded data is parsed in memory,
quality-checked, hourly-resampled, and passed through the same forecasting pipeline.

## Model accuracy

WattWise reports **MAE and RMSE on a chronological held-out test set** for the
actual dataset. It does not claim a universal accuracy percentage because forecast
quality is dataset-dependent. Expanding-window time-series validation is also available
for the Random Forest component.

## Known limitation to be aware of

Model retraining currently happens synchronously on request (`/train`,
or clicking "Run forecast" in the dashboard) — fine for a demo or a small
number of tenants, but a background job queue (Celery/RQ) would be the
next step before this scales to many companies training frequently.

---

## Where to add your own data and API keys

This is the one section to come back to before a real deployment —
everything below is a deliberately left-open integration point, not
something skipped by accident.

1. **A real consumption dataset** — drop a file in the UCI-style format
   (`Date;Time;Global_active_power;...`) into `data/`, named
   `household_power_consumption.txt`, or set `WATTWISE_DATA_FILE` in
   `.env` to a different filename. `data_loader.py` picks it up
   automatically instead of the synthetic demo data.

2. **Environment / secrets** — copy `.env.example` to `.env` and fill in
   real values (tariff rates for your actual DISCOM, `WATTWISE_ENV=production`
   for a real deployment, `REDIS_URL` once you move the rate limiter off
   in-process memory — see `security.py`).

3. **A real weather/solar generation API, or a real DISCOM/smart-meter
   API** — go to `src/external_apis.py`. It's a deliberately empty,
   clearly-labeled module with two stub functions
   (`get_solar_generation_forecast`, `fetch_latest_meter_reading`) and
   instructions in its own docstring for wiring either in. Nothing else
   in the codebase calls it yet — that's intentional, so a real
   integration has one obvious place to live instead of getting scattered
   across `api.py`/`app.py`/`forecast.py`.

4. **TLS certificate** — `nginx/wattwise.conf` references
   `nginx/certs/wattwise.crt` and `wattwise.key`, which don't exist yet.
   Generate these via Let's Encrypt/certbot or your organization's CA
   before exposing this beyond localhost.

5. **Database** — already handled. Leave `DATABASE_URL` blank for a local
   SQLite file, or set it to a Supabase *Session pooler* string for a
   shared online database (DEPLOYMENT.md, Part 2).


## Current release notes — September 2026

- Dashboard includes the **WhattsOn** tab and a regression test for its tab declaration.
- WhattsOn works without a key and can optionally use Gemini through `GEMINI_API_KEY` + `WATTWISE_USE_GEMINI=true`; failed Gemini calls fall back to deterministic answers.
- Supabase is the shared PostgreSQL backend. Raw CSV/TXT meter files are **not** automatically stored in Supabase; upload them through the dashboard or keep a private local `data/` file.
- Never commit `.env`, real meter/customer data, API keys, or the SQLite database.
