"""
savings.py
-----------
Cost and savings calculation: baseline cost vs. optimized cost if
peak-window consumption is partially shifted to off-peak hours.
"""

from __future__ import annotations
from dataclasses import dataclass

import pandas as pd

from .flags import TariffWindow


@dataclass
class SavingsResult:
    baseline_cost: float
    optimized_cost: float
    savings_amount: float
    savings_pct: float
    shifted_kwh: float
    detail_df: pd.DataFrame
    horizon_hours: int = 24

    @property
    def monthly_savings(self) -> float:
        """Savings scaled from the forecast horizon to a 30-day month. The horizon is hourly rows, so
        a 24h run is x30 and a 168h run is x(720/168). (Multiplying every horizon by 30 overstated a
        7-day forecast's monthly savings by 7x.)"""
        return self.savings_amount / max(self.horizon_hours, 1) * 24 * 30


def calculate_savings(
    flagged_df: pd.DataFrame,
    tariff: TariffWindow,
    shift_fraction: float = 0.3,
    value_col: str = "forecast_kw",
) -> SavingsResult:
    """
    flagged_df must already have 'tariff_band', 'tariff_rate', 'is_peak_flag'
    (i.e. output of flag_peak_hours).

    shift_fraction: fraction of peak-hour consumption assumed to be
    shiftable to off-peak hours (default 30%, matches project assumptions).

    Raises
    ------
    ValueError
        If required columns are missing or shift_fraction is out of [0, 1].
    """
    required_cols = {"tariff_band", "tariff_rate", "is_peak_flag", value_col}
    missing = required_cols - set(flagged_df.columns)
    if missing:
        raise ValueError(
            f"calculate_savings expects columns {sorted(required_cols)} — missing {sorted(missing)}. "
            "Did you run flag_peak_hours() first?"
        )
    if not (0.0 <= shift_fraction <= 1.0):
        raise ValueError(f"shift_fraction must be between 0 and 1, got {shift_fraction}.")

    df = flagged_df.copy()
    df["baseline_cost"] = df[value_col] * df["tariff_rate"]

    shiftable_kwh = df.loc[df["is_peak_flag"], value_col] * shift_fraction
    total_shifted = float(shiftable_kwh.sum())

    df["shifted_kwh"] = 0.0
    df.loc[df["is_peak_flag"], "shifted_kwh"] = shiftable_kwh

    remaining_peak = df[value_col] - df["shifted_kwh"]
    df["optimized_consumption"] = df[value_col]
    df.loc[df["is_peak_flag"], "optimized_consumption"] = remaining_peak.loc[df["is_peak_flag"]]

    # cost after shifting: remaining peak stays at peak rate,
    # shifted portion moves to off-peak rate
    df["optimized_cost"] = df["optimized_consumption"] * df["tariff_rate"]
    df.loc[df["is_peak_flag"], "optimized_cost"] = (
        df.loc[df["is_peak_flag"], "optimized_consumption"] * tariff.peak_rate
        + df.loc[df["is_peak_flag"], "shifted_kwh"] * tariff.off_peak_rate
    )

    baseline_total = float(df["baseline_cost"].sum())
    optimized_total = float(df["optimized_cost"].sum())
    savings = baseline_total - optimized_total
    savings_pct = (savings / baseline_total * 100) if baseline_total > 0 else 0.0

    return SavingsResult(
        baseline_cost=baseline_total,
        optimized_cost=optimized_total,
        savings_amount=savings,
        savings_pct=savings_pct,
        shifted_kwh=total_shifted,
        detail_df=df,
        horizon_hours=len(df),
    )
