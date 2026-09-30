"""
external_apis.py
------------------
THIS IS THE FILE TO EDIT WHEN YOU HAVE REAL API KEYS / INTEGRATIONS.

Nothing in this file is called by the rest of the pipeline yet — it's a
deliberately empty, clearly-labeled landing spot so a real integration
doesn't get scattered across api.py/app.py/forecast.py. Two integrations
this project's own planning discussion (the solar-panel question, the
"where does the data come from" question) pointed at:

1. WEATHER / SOLAR GENERATION FORECAST
   Needed for the "run heavy machinery on solar vs. grid" advisory
   mentioned in the project's original pitch script. A weather API
   (e.g. OpenWeatherMap, Open-Meteo, or a solar-specific forecast API)
   would let the consultant module compare forecasted grid demand
   against forecasted solar generation and recommend shifting load into
   daylight hours specifically. Wire it in here as a function like:

       def get_solar_generation_forecast(lat: float, lon: float, hours: int) -> list[float]:
           # call your chosen weather/solar API, return an hourly kW array
           raise NotImplementedError("Add your API key and endpoint here.")

   Then have consultant.py import and call it — do not add HTTP calls
   directly inside consultant.py, api.py, or app.py; keep every external
   network call behind this module so there's one place to see everything
   this system talks to over the internet, and one place to test it with
   a mock.

2. REAL DISCOM SMART-METER DATA
   If a DISCOM or an installed smart meter exposes a digital API instead
   of (or alongside) manual file exports, this is where a periodic pull
   job would live — e.g.:

       def fetch_latest_meter_reading(meter_id: str) -> dict:
           # call the DISCOM/meter vendor's API
           raise NotImplementedError("Add your API key and endpoint here.")

   The result should be shaped into the same ['datetime', 'Global_active_power']
   format data_loader.py already expects, so it can flow through the
   existing pipeline unchanged — see data_loader.py's _parse_uci_format
   for the exact shape.

WHERE TO PUT CREDENTIALS: never hardcode a key in this file. Add it to
.env (see .env.example) as e.g. WATTWISE_WEATHER_API_KEY=..., and read it
here with os.environ.get(...), the same pattern config.py already uses
for every other setting.
"""

from __future__ import annotations
import os


def get_solar_generation_forecast(lat: float, lon: float, hours: int = 24) -> list[float]:
    """
    TODO: implement once a weather/solar API key is available.
    Should return `hours` hourly estimated solar generation values (kW).
    """
    api_key = os.environ.get("WATTWISE_WEATHER_API_KEY")
    if not api_key:
        raise NotImplementedError(
            "No WATTWISE_WEATHER_API_KEY configured. Add a real weather/solar API "
            "integration here, and the key to your .env file, before calling this."
        )
    raise NotImplementedError("Weather/solar API call not yet implemented — see this file's module docstring.")


def fetch_latest_meter_reading(meter_id: str) -> dict:
    """
    TODO: implement once a real DISCOM/smart-meter API is available.
    Should return {"datetime": <ISO string>, "Global_active_power": <float kW>}.
    """
    api_key = os.environ.get("WATTWISE_METER_API_KEY")
    if not api_key:
        raise NotImplementedError(
            "No WATTWISE_METER_API_KEY configured. Add a real meter/DISCOM API "
            "integration here, and the key to your .env file, before calling this."
        )
    raise NotImplementedError("Meter API call not yet implemented — see this file's module docstring.")
