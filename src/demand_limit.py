"""
demand_limit.py
-----------------
Detects forecasted breaches of a facility's sanctioned load (a.k.a.
"contract demand") — the maximum kW a commercial/institutional connection
is allowed to draw under its DISCOM agreement.

Why this matters (and why it's separate from peak-tariff flagging):
ToD tariff flags are about paying MORE per unit during expensive hours.
A sanctioned-load breach is a different, harsher problem — DISCOMs charge
a separate penalty (often per kVA of the excess, sometimes a multiple of
the normal demand charge) for exceeding the contracted limit, and repeated
breaches can trigger a load audit or forced contract-demand revision.
"""

from __future__ import annotations
from dataclasses import dataclass

import pandas as pd


class InvalidDemandLimitError(ValueError):
    """Raised when a sanctioned load / penalty configuration doesn't make sense."""


@dataclass
class DemandLimitConfig:
    sanctioned_load_kw: float
    penalty_rate_per_kw: float = 150.0   # ₹ per kW of excess demand, illustrative
    warning_margin_pct: float = 10.0     # warn when within this % of the limit, before breach

    def __post_init__(self):
        if self.sanctioned_load_kw <= 0:
            raise InvalidDemandLimitError("sanctioned_load_kw must be positive.")
        if self.penalty_rate_per_kw < 0:
            raise InvalidDemandLimitError("penalty_rate_per_kw cannot be negative.")
        if not (0 <= self.warning_margin_pct <= 100):
            raise InvalidDemandLimitError("warning_margin_pct must be between 0 and 100.")

    @property
    def warning_threshold_kw(self) -> float:
        return self.sanctioned_load_kw * (1 - self.warning_margin_pct / 100)


def flag_demand_breaches(
    df: pd.DataFrame,
    config: DemandLimitConfig,
    value_col: str = "forecast_kw",
) -> pd.DataFrame:
    """
    Adds three columns to df:
      - demand_status: "Breach" | "Warning" | "Normal"
      - excess_kw: how far over the sanctioned limit (0 if not breaching)
      - estimated_penalty: excess_kw * penalty_rate_per_kw (0 if not breaching)
    """
    if value_col not in df.columns:
        raise ValueError(f"flag_demand_breaches expects a '{value_col}' column.")

    out = df.copy()

    def _status(v: float) -> str:
        if v > config.sanctioned_load_kw:
            return "Breach"
        if v >= config.warning_threshold_kw:
            return "Warning"
        return "Normal"

    out["demand_status"] = out[value_col].apply(_status)
    out["excess_kw"] = (out[value_col] - config.sanctioned_load_kw).clip(lower=0)
    out["estimated_penalty"] = out["excess_kw"] * config.penalty_rate_per_kw
    return out


@dataclass
class DemandSummary:
    breach_hours: int
    warning_hours: int
    peak_forecast_kw: float
    total_estimated_penalty: float
    first_breach_time: pd.Timestamp | None


def summarize_demand_risk(flagged_df: pd.DataFrame, value_col: str = "forecast_kw") -> DemandSummary:
    breaches = flagged_df[flagged_df["demand_status"] == "Breach"]
    warnings = flagged_df[flagged_df["demand_status"] == "Warning"]
    return DemandSummary(
        breach_hours=int(len(breaches)),
        warning_hours=int(len(warnings)),
        peak_forecast_kw=float(flagged_df[value_col].max()),
        total_estimated_penalty=float(flagged_df["estimated_penalty"].sum()),
        first_breach_time=breaches["datetime"].iloc[0] if len(breaches) else None,
    )
