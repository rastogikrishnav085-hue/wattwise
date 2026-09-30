"""
flags.py
---------
Peak-tariff flagging and statistical anomaly detection.

Anomaly detection now accepts an optional shift_pattern. Without it, a
shift-change surge (every machine on a floor starting at once) reads as
a statistical anomaly, which is a real false-positive source the
previous version had no way to suppress and no test caught, because the
household-shaped demo data has no shift boundaries to expose it.
"""

from __future__ import annotations
from dataclasses import dataclass, field

import pandas as pd

from .config import TARIFF_DEFAULTS, MODEL_DEFAULTS
from .features import compute_shift_flags


class InvalidTariffError(ValueError):
    """Raised when a TariffWindow's hours or rates don't make physical sense."""


@dataclass
class TariffWindow:
    peak_hours: tuple = (TARIFF_DEFAULTS.peak_start, TARIFF_DEFAULTS.peak_end)
    shoulder_hours: tuple = (TARIFF_DEFAULTS.shoulder_start, TARIFF_DEFAULTS.shoulder_end)
    peak_rate: float = TARIFF_DEFAULTS.peak_rate
    shoulder_rate: float = TARIFF_DEFAULTS.shoulder_rate
    off_peak_rate: float = TARIFF_DEFAULTS.off_peak_rate

    def __post_init__(self):
        for label, hours in (("peak_hours", self.peak_hours), ("shoulder_hours", self.shoulder_hours)):
            if len(hours) != 2 or not (0 <= hours[0] < hours[1] <= 24):
                raise InvalidTariffError(
                    f"{label}={hours} must be a (start, end) pair with 0 <= start < end <= 24."
                )
        if any(rate <= 0 for rate in (self.peak_rate, self.shoulder_rate, self.off_peak_rate)):
            raise InvalidTariffError("Tariff rates must be positive.")
        if not (self.peak_rate >= self.shoulder_rate >= self.off_peak_rate):
            raise InvalidTariffError(
                f"Expected peak_rate ({self.peak_rate}) >= shoulder_rate ({self.shoulder_rate}) "
                f">= off_peak_rate ({self.off_peak_rate}) — a ToD tariff structure that charges more "
                "off-peak than on-peak isn't a valid input for this model."
            )

    def rate_for_hour(self, hour: int) -> float:
        if self.peak_hours[0] <= hour < self.peak_hours[1]:
            return self.peak_rate
        if self.shoulder_hours[0] <= hour < self.shoulder_hours[1]:
            return self.shoulder_rate
        return self.off_peak_rate

    def band_for_hour(self, hour: int) -> str:
        if self.peak_hours[0] <= hour < self.peak_hours[1]:
            return "Peak"
        if self.shoulder_hours[0] <= hour < self.shoulder_hours[1]:
            return "Shoulder"
        return "Off-Peak"


def flag_peak_hours(df: pd.DataFrame, tariff: TariffWindow, value_col: str = "forecast_kw") -> pd.DataFrame:
    """Adds tariff band, rate, and a boolean 'is_peak_flag' column.

    Deliberately independent of demand_limit.py's flag_demand_breaches: this
    function only ever looks at the clock hour (cost), never the kW value
    (consumption) — see demand_limit.py for the consumption-side check.
    """
    if "datetime" not in df.columns:
        raise ValueError("flag_peak_hours expects a 'datetime' column.")
    out = df.copy()
    out["hour"] = out["datetime"].dt.hour
    out["tariff_band"] = out["hour"].apply(tariff.band_for_hour)
    out["tariff_rate"] = out["hour"].apply(tariff.rate_for_hour)
    out["is_peak_flag"] = out["tariff_band"] == "Peak"
    return out


def detect_anomalies(
    df: pd.DataFrame,
    value_col: str = "forecast_kw",
    z_thresh: float = MODEL_DEFAULTS.anomaly_z_thresh_forecast,
    shift_pattern=None,
) -> pd.DataFrame:
    """
    Flags rows where consumption deviates more than `z_thresh` standard
    deviations from the mean of the series (simple global z-score check).
    Used on short (e.g. 24h) windows where a rolling window isn't long
    enough to be meaningful.

    If shift_pattern is given and a 'datetime' column is present, hours
    within a shift boundary (per features.compute_shift_flags) are excluded
    from being flagged — a shift-start/end surge is expected load behavior,
    not a fault.
    """
    out = df.copy()
    mean = out[value_col].mean()
    std = out[value_col].std(ddof=0) or 1e-6
    out["z_score"] = (out[value_col] - mean) / std
    out["is_anomaly"] = out["z_score"].abs() > z_thresh

    if shift_pattern is not None and "datetime" in out.columns:
        hours = out["datetime"].dt.hour
        _, boundary = compute_shift_flags(hours, shift_pattern)
        out.loc[boundary.astype(bool), "is_anomaly"] = False

    return out


def detect_rolling_anomalies(
    df: pd.DataFrame,
    value_col: str = "Global_active_power",
    window: int = 24,
    z_thresh: float = MODEL_DEFAULTS.anomaly_z_thresh_historical,
    shift_pattern=None,
) -> pd.DataFrame:
    """
    Rolling-window z-score anomaly detection over a longer historical
    series (centered 24h window, threshold 2.5σ by default). This is the
    method used against real consumption history, as opposed to
    `detect_anomalies` which handles short forecast windows.

    Same shift_pattern suppression as detect_anomalies — without it, every
    shift change in a multi-day history gets flagged, which drowns out the
    genuine anomalies the anomaly count is supposed to surface.
    """
    out = df.copy().sort_values("datetime").reset_index(drop=True)
    roll_mean = out[value_col].rolling(window=window, center=True).mean()
    roll_std = out[value_col].rolling(window=window, center=True).std()
    z = (out[value_col] - roll_mean) / roll_std.replace(0, 1e-6)
    out["z_score"] = z
    out["is_anomaly"] = z.abs() > z_thresh
    out["is_anomaly"] = out["is_anomaly"].fillna(False)

    if shift_pattern is not None:
        hours = out["datetime"].dt.hour
        _, boundary = compute_shift_flags(hours, shift_pattern)
        out.loc[boundary.astype(bool), "is_anomaly"] = False

    return out
