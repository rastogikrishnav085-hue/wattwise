# WattWise + Gemini / WhattsOn

WhattsOn has two modes:

1. **Deterministic mode** — no external API key required; safest for offline demos.
2. **Gemini mode** — optional natural-language enhancement using the official Google GenAI Python SDK.

## Enable Gemini locally
1. Create a Gemini API key in Google AI Studio.
2. Copy `.env.example` to `.env`.
3. Set:

`GEMINI_API_KEY=YOUR_REAL_KEY`
`WATTWISE_USE_GEMINI=true`
`GEMINI_MODEL=gemini-3.8-flash`

4. Restart WattWise.

The key must never be committed to GitHub. `.env` is ignored by `.gitignore`.

If the Gemini request fails, WhattsOn automatically falls back to the deterministic assistant instead of crashing the dashboard.
