"""
config.py
----------
Single source of truth for paths, tariff defaults, and model hyperparameters.

Every value here can be overridden with an environment variable, so the
same code runs unchanged in dev, in a demo, or wired into a real deployment
without editing source files.
"""

from __future__ import annotations
import os
from dataclasses import dataclass, field

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Load a local .env file if one exists, so the "copy .env.example to .env" instructions
# actually work when running outside Docker. Real environment variables always win
# (Render / Streamlit Cloud set theirs directly and have no .env file).
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, ".env"), override=False)
except ImportError:  # python-dotenv is optional; env vars still work without it
    pass
DATA_DIR = os.path.join(BASE_DIR, "data")
MODEL_DIR = os.path.join(BASE_DIR, "models")

RAW_DATA_FILENAME = os.environ.get("WATTWISE_DATA_FILE", "household_power_consumption.txt")
RAW_DATA_PATH = os.path.join(DATA_DIR, RAW_DATA_FILENAME)

# Database connection string. Unset = a local SQLite file (zero setup, used for
# local runs and the test suite). Set it to a Postgres URL (e.g. the connection
# string a free Supabase project gives you) to switch backends with no code
# changes — see database.py's module docstring for why this matters on free hosts.
DATABASE_URL = os.environ.get("DATABASE_URL") or f"sqlite:///{os.path.join(DATA_DIR, 'wattwise.db')}"

RF_MODEL_PATH = os.path.join(MODEL_DIR, "rf_model.pkl")
ARIMA_MODEL_PATH = os.path.join(MODEL_DIR, "arima_model.pkl")
MODEL_METADATA_PATH = os.path.join(MODEL_DIR, "model_metadata.json")


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class TariffDefaults:
    peak_start: int = _int_env("WATTWISE_PEAK_START", 18)
    peak_end: int = _int_env("WATTWISE_PEAK_END", 22)
    shoulder_start: int = _int_env("WATTWISE_SHOULDER_START", 10)
    shoulder_end: int = _int_env("WATTWISE_SHOULDER_END", 13)
    peak_rate: float = _float_env("WATTWISE_PEAK_RATE", 12.0)
    shoulder_rate: float = _float_env("WATTWISE_SHOULDER_RATE", 7.0)
    off_peak_rate: float = _float_env("WATTWISE_OFF_PEAK_RATE", 4.0)


@dataclass(frozen=True)
class ModelDefaults:
    rf_n_estimators: int = _int_env("WATTWISE_RF_TREES", 80)
    rf_max_depth: int = _int_env("WATTWISE_RF_MAX_DEPTH", 12)
    arima_order_candidates: tuple = ((1, 1, 1), (2, 1, 2), (1, 1, 0), (2, 1, 0))
    min_training_rows: int = _int_env("WATTWISE_MIN_TRAIN_ROWS", 200)
    anomaly_z_thresh_forecast: float = _float_env("WATTWISE_ANOMALY_Z_FORECAST", 2.0)
    anomaly_z_thresh_historical: float = _float_env("WATTWISE_ANOMALY_Z_HISTORICAL", 2.5)
    cv_splits: int = _int_env("WATTWISE_CV_SPLITS", 5)
    ci_level: float = _float_env("WATTWISE_CI_LEVEL", 0.9)


TARIFF_DEFAULTS = TariffDefaults()
MODEL_DEFAULTS = ModelDefaults()

LOG_LEVEL = os.environ.get("WATTWISE_LOG_LEVEL", "INFO")

# --- MSME industry benchmarks used by consultant.py's strategic tier ---
#
# THESE ARE PLACEHOLDER ESTIMATES, not measured figures — there is no real
# MSME dataset behind this project yet. They exist so the strategic
# advisory tier has *some* reference point to compare a company's own
# trend against, and every message that uses them is worded as an
# estimate (see consultant.py). Replace with real figures once available
# from actual MSME energy audits, and do not present these numbers as
# verified to a judge, teacher, or customer until they are.
INDUSTRY_BENCHMARKS_ESTIMATED = {
    "textile": {"typical_load_factor": 0.55, "typical_shift_count": 2},
    "plastics": {"typical_load_factor": 0.65, "typical_shift_count": 3},
    "metal_fabrication": {"typical_load_factor": 0.50, "typical_shift_count": 1},
    "food_processing": {"typical_load_factor": 0.60, "typical_shift_count": 2},
}
