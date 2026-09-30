"""
data_loader.py
--------------
Handles loading of household/MSME electricity consumption data.

REAL DATA MODE (for actual submission):
    Point WATTWISE_DATA_FILE at a real electricity dataset in data/. The
    loader supports the canonical UCI Date;Time;Global_active_power format
    plus common MSME CSV exports with timestamp/datetime and load/power/demand
    columns.

DEMO MODE (for development / testing without real data):
    If no real data file is found, generates a synthetic hourly series.
    Two demo "shapes" are available via `scenario`:
      - "normal" / "high_demand" / "anomaly_heavy": the original
        household-shaped curve (two Gaussian daily bumps) — kept for
        backward compatibility and for demoing against the UCI dataset's
        actual shape.
      - "msme_shift": a shift-driven curve — flat and elevated during
        configured shift hours, near-idle outside them, and mostly idle
        on weekends (a factory floor, not a home). Use this scenario
        when demoing the MSME-specific framing of this project — the
        household scenarios understate how different a real factory's
        load profile looks, which matters if a judge or teacher compares
        the demo shape to what they'd expect from an MSME.

    Clearly flagged via `DataSource` in the returned metadata so nothing
    is silently passed off as real data.
"""

from __future__ import annotations
import io
import os
from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd

from .config import RAW_DATA_PATH
from .data_quality import validate_or_raise, assess_quality, DataQualityError
from .features import compute_shift_flags, DEFAULT_SHIFT_PATTERN
from .logging_setup import get_logger

log = get_logger(__name__)

ALLOWED_UPLOAD_EXTENSIONS = (".txt", ".csv")
MAX_UPLOAD_SIZE_MB = 50

SCENARIOS = ("normal", "high_demand", "anomaly_heavy", "msme_shift")


class DataSource(str, Enum):
    REAL_UCI = "real_uci_dataset"
    DEMO_SYNTHETIC = "demo_synthetic_dataset"
    UPLOADED = "uploaded_dataset"


class DataLoadError(Exception):
    """Raised when a data file exists but can't be parsed into a usable series."""


@dataclass
class LoadResult:
    df: pd.DataFrame
    source: DataSource
    quality: object = None  # QualityReport, when quality checks ran (real/uploaded data); None for synthetic


def _parse_generic_format(df: pd.DataFrame, label: str) -> pd.DataFrame:
    """Normalize common MSME CSV exports to datetime + Global_active_power.

    Accepted timestamp patterns include a single datetime/timestamp column or
    separate Date/Time columns. Common consumption names include power, load,
    demand, consumption and kW variants. The normalized target is kept as
    Global_active_power so the existing forecasting pipeline remains unchanged.
    """
    columns = {str(c).strip().lower(): c for c in df.columns}
    timestamp_col = next((columns[k] for k in ("datetime", "timestamp", "date_time", "date time", "time_stamp") if k in columns), None)
    if timestamp_col is not None:
        dt = pd.to_datetime(df[timestamp_col], dayfirst=False, errors="coerce")
    elif "date" in columns and "time" in columns:
        dt = pd.to_datetime(
            df[columns["date"]].astype(str) + " " + df[columns["time"]].astype(str),
            dayfirst=True, errors="coerce",
        )
    else:
        raise DataLoadError(
            f"{label} must contain either a datetime/timestamp column or separate Date and Time columns."
        )

    value_candidates = (
        "global_active_power", "active_power", "power_kw", "power (kw)",
        "load_kw", "load (kw)", "demand_kw", "demand (kw)",
        "consumption", "energy_consumption", "power", "load", "demand", "kw",
    )
    value_col = next((columns[k] for k in value_candidates if k in columns), None)
    if value_col is None:
        raise DataLoadError(
            f"{label} has no recognizable electricity-consumption column. Expected a column such as "
            "Global_active_power, power_kw, load_kw, demand_kw, consumption or power."
        )

    out = pd.DataFrame({"datetime": dt, "Global_active_power": pd.to_numeric(df[value_col], errors="coerce")})
    out = out.dropna(subset=["datetime", "Global_active_power"]).sort_values("datetime")
    if out.empty:
        raise DataLoadError(f"{label} contains no valid timestamped consumption readings.")
    out = out.set_index("datetime").resample("1h").mean().dropna().reset_index()
    if len(out) < 48:
        raise DataLoadError(
            f"{label} resolved to only {len(out)} hourly rows after cleaning — too little "
            "history to train a meaningful forecasting model (need at least 48)."
        )
    return out


def _parse_uci_format(buffer_or_path, label: str) -> pd.DataFrame:
    """Shared parsing logic for the UCI-style format, used for both a real
    filesystem path and an in-memory uploaded buffer."""
    try:
        df = pd.read_csv(buffer_or_path, sep=";", low_memory=False)
        # Common MSME exports are comma-separated. If the semicolon parser sees
        # one giant column, rewind in-memory buffers and try comma-separated CSV.
        if len(df.columns) == 1 and isinstance(buffer_or_path, io.BytesIO):
            buffer_or_path.seek(0)
            comma_df = pd.read_csv(buffer_or_path, sep=",", low_memory=False)
            if len(comma_df.columns) > 1:
                df = comma_df
    except Exception as exc:  # noqa: BLE001 — re-raised with context regardless of cause
        raise DataLoadError(f"Could not parse {label} as a CSV. Original error: {exc}") from exc

    # Prefer the canonical UCI schema, then fall back to common MSME export names.
    if not ({"Date", "Time", "Global_active_power"} <= set(df.columns)):
        return _parse_generic_format(df, label)

    df["datetime"] = pd.to_datetime(
        df["Date"].astype(str) + " " + df["Time"].astype(str),
        dayfirst=True, errors="coerce",
    )
    n_bad_dates = int(df["datetime"].isna().sum())
    df = df.dropna(subset=["datetime"])
    if df.empty:
        raise DataLoadError(f"{label}: no rows had a parseable Date/Time (expected DD/MM/YYYY and HH:MM:SS).")
    if n_bad_dates:
        log.warning("%s: dropped %s rows with unparseable Date/Time", label, n_bad_dates)

    df.replace("?", np.nan, inplace=True)
    df = df.dropna(subset=["Global_active_power"])
    if df.empty:
        raise DataLoadError(f"{label} contained no valid (non-missing) power readings after cleaning.")

    df["Global_active_power"] = pd.to_numeric(df["Global_active_power"], errors="coerce")
    df = df.dropna(subset=["Global_active_power"])
    df = df[["datetime", "Global_active_power"]].sort_values("datetime").reset_index(drop=True)

    df = df.set_index("datetime").resample("1h").mean().dropna().reset_index()

    if len(df) < 48:
        raise DataLoadError(
            f"{label} resolved to only {len(df)} hourly rows after cleaning — too little "
            "history to train a meaningful forecasting model (need at least 48)."
        )

    return df


def _load_real_uci(path: str) -> tuple[pd.DataFrame, object]:
    df = _parse_uci_format(path, label=path)
    try:
        quality = validate_or_raise(df, label=f"real dataset at {path}")
    except DataQualityError as exc:
        raise DataLoadError(str(exc)) from exc
    for w in quality.warnings:
        log.warning("%s: %s", path, w)
    log.info("Loaded real dataset: %s hourly rows from %s", len(df), path)
    return df, quality


def load_from_upload(file_bytes: bytes, filename: str) -> LoadResult:
    """
    Loads a user-uploaded dataset from raw bytes. Untrusted input, handled
    accordingly:
      - Extension checked against an allowlist before any parsing.
      - Size capped (MAX_UPLOAD_SIZE_MB) against memory-exhaustion DoS.
      - Parsed entirely in memory — never written to disk under a
        user-supplied filename (no path-traversal/filename-injection risk).
      - Parsing failures raise DataLoadError without echoing raw file content.
    """
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise DataLoadError(
            f"Unsupported file type '{ext or '(none)'}' — expected one of {ALLOWED_UPLOAD_EXTENSIONS}."
        )

    size_mb = len(file_bytes) / (1024 * 1024)
    if size_mb > MAX_UPLOAD_SIZE_MB:
        raise DataLoadError(
            f"Uploaded file is {size_mb:.1f} MB, which exceeds the {MAX_UPLOAD_SIZE_MB} MB limit."
        )
    if len(file_bytes) == 0:
        raise DataLoadError("Uploaded file is empty.")

    buffer = io.BytesIO(file_bytes)
    df = _parse_uci_format(buffer, label=f"uploaded file '{filename}'")
    try:
        quality = validate_or_raise(df, label=f"uploaded file '{filename}'")
    except DataQualityError as exc:
        raise DataLoadError(str(exc)) from exc
    for w in quality.warnings:
        log.warning("uploaded file '%s': %s", filename, w)
    log.info("Loaded uploaded dataset '%s': %s hourly rows (%.1f MB)", filename, len(df), size_mb)
    return LoadResult(df=df, source=DataSource.UPLOADED, quality=quality)


# Where the near-peak (97th percentile) hour of a demo series lands, as a multiple of the
# company's sanctioned load, when demo data is scaled to that company. Real factories run close
# to their contract limit, so the MSME shape sits near 1.0 (a few warning hours, the odd
# breach); "high_demand" is the deliberate stress test that breaches for the penalty demo.
_DEMO_PEAK_RATIO = {
    "msme_shift": 1.05, "normal": 0.95, "high_demand": 1.60, "anomaly_heavy": 1.00,
}


def _scale_to_sanctioned_load(df: pd.DataFrame, sanctioned_load_kw: float, scenario: str) -> pd.DataFrame:
    """Rescales a unit-scale demo series so it looks like *this* company's load. Without this a
    100 kW factory is shown ~1 kW of demand: no breach is ever possible and every rupee figure
    is tiny. Only used for synthetic demo data - real/uploaded data is never rescaled."""
    out = df.copy()
    p97 = float(np.percentile(out["Global_active_power"], 97))
    if p97 <= 0:
        return out
    ratio = _DEMO_PEAK_RATIO.get(scenario, 1.0)
    out["Global_active_power"] = out["Global_active_power"] * (sanctioned_load_kw * ratio / p97)
    return out


def _anchor_series_to_today(df: pd.DataFrame) -> pd.DataFrame:
    """Shifts a demo series in time so it ends at the last full hour before now. Otherwise the
    forecast is dated after the fixed demo start (April 2024), which looks broken on a dashboard."""
    out = df.copy()
    end = pd.Timestamp.now().floor("h") - pd.Timedelta(hours=1)
    n = len(out)
    out["datetime"] = pd.date_range(end=end, periods=n, freq="h")
    return out


def _generate_demo_series(
    start: str = "2024-01-01",
    periods_days: int = 120,
    seed: int = 42,
    scenario: str = "normal",
    shift_pattern=None,
) -> pd.DataFrame:
    """
    Generates an hourly synthetic consumption series. NOT real data — exists
    so the pipeline can be developed and demoed before real data is plugged in.
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario '{scenario}' — expected one of {SCENARIOS}.")

    rng = np.random.default_rng(seed)
    hours = periods_days * 24
    idx = pd.date_range(start=start, periods=hours, freq="h")

    hour_of_day = idx.hour.values
    day_of_week = idx.dayofweek.values
    day_index = np.arange(hours) / 24.0

    if scenario == "msme_shift":
        pattern = shift_pattern or DEFAULT_SHIFT_PATTERN
        shift_active, _ = compute_shift_flags(pd.Series(hour_of_day), pattern)
        shift_active = shift_active.values.astype(float)

        # Flat elevated block during shift hours, low idle load outside — this is
        # the shape a factory floor actually has, unlike the household double-bump.
        daily_shape = 0.12 + 0.85 * shift_active
        # Most MSMEs run a lighter schedule or are closed on weekends — the
        # opposite of a household, which tends to use MORE power on weekends.
        weekend_boost = np.where(day_of_week >= 5, 0.25, 1.0)
        seasonal_drift = 1.0 + 0.08 * np.sin(2 * np.pi * day_index / 180)
        noise = rng.normal(0, 0.05, size=hours)

        consumption = daily_shape * weekend_boost * seasonal_drift + noise
        # Shift-start surges: a real, larger, expected jump exactly at shift-start
        # hours (simultaneous machine start-up) — this is what features.py's
        # shift_boundary_flag and flags.py's suppression logic are meant to handle.
        _, shift_boundary = compute_shift_flags(pd.Series(hour_of_day), pattern)
        consumption[shift_boundary.values.astype(bool)] *= rng.uniform(1.3, 1.6, size=int(shift_boundary.sum()))

        anomaly_prob = 0.006
        anomaly_scale = (1.6, 2.2)
    else:
        daily_shape = (
            0.35
            + 0.55 * np.exp(-0.5 * ((hour_of_day - 19) / 2.2) ** 2)   # evening peak ~7pm
            + 0.25 * np.exp(-0.5 * ((hour_of_day - 8) / 1.8) ** 2)    # morning bump ~8am
        )
        weekend_boost = np.where(day_of_week >= 5, 1.12, 1.0)
        seasonal_drift = 1.0 + 0.15 * np.sin(2 * np.pi * day_index / 180)
        noise = rng.normal(0, 0.06, size=hours)
        consumption = daily_shape * weekend_boost * seasonal_drift + noise

        anomaly_prob = 0.005
        anomaly_scale = (1.8, 2.6)
        if scenario == "high_demand":
            consumption *= 1.65
        elif scenario == "anomaly_heavy":
            anomaly_prob = 0.035

    consumption = np.clip(consumption, 0.05, None)
    anomaly_mask = rng.random(hours) < anomaly_prob
    consumption[anomaly_mask] *= rng.uniform(*anomaly_scale, size=anomaly_mask.sum())

    df = pd.DataFrame({"datetime": idx, "Global_active_power": consumption})
    log.info("Generated synthetic demo dataset (scenario=%s): %s hourly rows", scenario, len(df))
    return df


def load_consumption_data(
    force_demo: bool = False,
    scenario: str = "normal",
    shift_pattern=None,
    sanctioned_load_kw: float | None = None,
    anchor_to_today: bool = False,
) -> LoadResult:
    """
    Main entry point. Returns hourly consumption data + which source was used.

    scenario: "normal" | "high_demand" | "anomaly_heavy" | "msme_shift".
        Ignored when loading a real file. Pass "msme_shift" plus the
        company's real shift_pattern (from the companies table) to demo
        against data shaped like an actual factory, not a household.
    shift_pattern: only used when scenario == "msme_shift"; ignored otherwise.
    sanctioned_load_kw: demo data only - rescale the synthetic series to this company's size.
    anchor_to_today: demo data only - end the series at the current hour instead of Apr 2024.

    Raises
    ------
    DataLoadError
        If a real data file is present but malformed — intentionally NOT
        swallowed into a silent fallback to synthetic data.
    """
    if not force_demo and os.path.exists(RAW_DATA_PATH):
        df, quality = _load_real_uci(RAW_DATA_PATH)
        return LoadResult(df=df, source=DataSource.REAL_UCI, quality=quality)

    df = _generate_demo_series(scenario=scenario, shift_pattern=shift_pattern)
    if sanctioned_load_kw and sanctioned_load_kw > 0:
        df = _scale_to_sanctioned_load(df, float(sanctioned_load_kw), scenario)
    if anchor_to_today:
        df = _anchor_series_to_today(df)
    return LoadResult(df=df, source=DataSource.DEMO_SYNTHETIC)


if __name__ == "__main__":
    result = load_consumption_data()
    print(f"Source: {result.source.value}")
    print(result.df.head())
    print(f"Shape: {result.df.shape}")
