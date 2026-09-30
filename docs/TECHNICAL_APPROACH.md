# WattWise — Technical Approach

WattWise is an end-to-end AI-powered energy intelligence platform for MSMEs.

**MSME data → Quality Gate → Feature Engineering → Random Forest + ARIMA → Validated Forecast → Confidence Intervals → Anomaly Detection → Tariff & Sanctioned-Load Analysis → Savings/Risk Engine → Explainable Recommendations → WhattsOn → Streamlit/FastAPI → SQLite/Supabase PostgreSQL → Reports**

## Data

WattWise supports synthetic demo scenarios, real UCI-format electricity data, and user-uploaded `.csv`/`.txt` datasets. Uploaded data is validated before forecasting and is never silently treated as real if it is synthetic.

## Forecasting

- Pandas/NumPy/SciPy for data and statistics.
- Random Forest via scikit-learn for non-linear feature-driven demand patterns.
- ARIMA via statsmodels for temporal structure.
- ARIMA order selected by held-out test error.
- Ensemble weights selected by held-out MAE.
- ARIMA can receive 0% weight when blending hurts accuracy.
- Chronological 80/20 evaluation.
- MAE and RMSE are reported for the actual dataset.
- Expanding-window time-series validation is available for Random Forest.
- Forecast horizon: approximately 24–168 hours in the dashboard.
- 80/90/95% confidence intervals.

## MSME intelligence

- Hour/day/week and shift-aware features.
- Forecast and historical anomaly detection using z-scores and rolling z-scores.
- Shift-boundary suppression to reduce predictable industrial false alarms.
- Peak/shoulder/off-peak tariff classification.
- Configurable peak-load shifting simulation.
- Configurable sanctioned-load threshold and breach/warning detection.
- Illustrative ₹150/kW penalty assumption and 30% shiftable-load assumption are explicitly configurable, not universal DISCOM figures.
- Industry-specific rule-based recommendations.
- Consultant layer for trending and strategic insights.
- Human-in-the-loop: recommendations are advisory; WattWise does not directly control industrial equipment.

## Application and infrastructure

- FastAPI + Uvicorn + Pydantic backend.
- Streamlit + Plotly dashboard.
- SQLAlchemy database abstraction.
- SQLite locally.
- PostgreSQL through Supabase in cloud deployment.
- Hashed per-company API keys, tenant isolation, rate limiting and audit logs.
- PDF via fpdf2 and Markdown reports.
- Docker, Docker Compose, Nginx, Render, Streamlit Cloud and GitHub Actions.
- 142 automated tests using pytest, HTTPX and Streamlit AppTest.
- Redis is included as a future shared rate-limiting layer; it is not the current active limiter.

## WhattsOn

WhattsOn is the conversational layer. It answers questions about the latest forecast, risk, savings, anomalies, model metrics, recommendations and consultant insights using structured WattWise context. The current implementation is provider-agnostic and does not require an external LLM API key; a future LLM provider can be placed behind the same interface.
