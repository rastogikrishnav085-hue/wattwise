# WhattsOn — WattWise Energy Assistant

WhattsOn is WattWise's conversational interface for MSME operators. It answers natural-language questions from the **latest structured WattWise results** rather than generating unsupported energy facts.

## Current implementation

The current project includes a lightweight, deterministic assistant in `src/whatts_on.py` and exposes it through:

- The Streamlit **WhattsOn** tab.
- `POST /whatts-on` in the FastAPI service.

It can explain:

- Forecast cost / tariff drivers
- Sanctioned-load warnings and breaches
- Estimated savings from load shifting
- Forecast and historical anomalies
- MAE/RMSE model performance and ensemble weights
- Current recommendations
- Consultant/trend insights
- Whether the current run used uploaded or demo data

## Why it is designed this way

WhattsOn is deliberately provider-agnostic. It works without an external LLM API key and only answers from WattWise's structured context. A future LLM provider can be added behind the same `answer()` interface without changing the dashboard or API contract.

## Important distinction

WhattsOn is **not a direct industrial-control agent**. It is an explanation and decision-support interface. Final operating decisions remain with the MSME operator.
