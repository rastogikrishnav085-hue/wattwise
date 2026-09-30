"""
features.py
------------
Temporal feature engineering for the forecasting models.

Now shift-aware instead of household-shaped. The old is_working_hours
flag (a flat 9-17 window) assumed a household/office pattern. An MSME
runs on shifts — 1, 2, or 3 per day, sometimes overnight — and the real
signal a forecaster needs isn't "is it daytime," it's "is a shift
active right now, and are we at a shift boundary" (where genuine load
surges/drops happen and should not be treated as anomalies downstream).
"""

from __future__ import annotations
import pandas as pd

# Fallback when a company has no shift_pattern configured yet — matches
# the old is_working_hours window so nothing breaks for an unconfigured company.
DEFAULT_SHIFT_PATTERN = [("09:00", "17:00")]


class InvalidShiftPatternError(ValueError):
    """Raised when a shift_pattern is malformed or out of range."""


def validate_shift_pattern(shift_pattern) -> None:
    """
    Raises InvalidShiftPatternError with a specific, actionable message if
    shift_pattern isn't a list of (HH:MM, HH:MM) pairs with valid hours.
    Call this at signup time (or wherever a shift_pattern is first
    accepted from a user) so a typo fails immediately with a clear
    message, instead of surfacing later as a confusing raw ValueError
    from deep inside feature engineering.
    """
    if shift_pattern is None:
        return
    if not isinstance(shift_pattern, (list, tuple)) or len(shift_pattern) == 0:
        raise InvalidShiftPatternError("shift_pattern must be a non-empty list of (start, end) pairs.")

    for i, pair in enumerate(shift_pattern):
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise InvalidShiftPatternError(f"Shift {i + 1}: expected a (start, end) pair, got {pair!r}.")
        for label, value in (("start", pair[0]), ("end", pair[1])):
            parts = str(value).split(":")
            if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
                raise InvalidShiftPatternError(
                    f"Shift {i + 1} {label} time '{value}' isn't in HH:MM format (e.g. '09:00')."
                )
            hour, minute = int(parts[0]), int(parts[1])
            if not (0 <= hour <= 24) or not (0 <= minute < 60):
                raise InvalidShiftPatternError(
                    f"Shift {i + 1} {label} time '{value}' is out of range — hour must be 0-24, minute 0-59."
                )


def _parse_shift_pattern(shift_pattern) -> list[tuple[int, int]]:
    if not shift_pattern:
        shift_pattern = DEFAULT_SHIFT_PATTERN
    validate_shift_pattern(shift_pattern)
    parsed = []
    for start_str, end_str in shift_pattern:
        start_h = int(str(start_str).split(":")[0])
        end_h = int(str(end_str).split(":")[0])
        parsed.append((start_h, end_h))
    return parsed


def compute_shift_flags(hour_series: pd.Series, shift_pattern=None) -> tuple[pd.Series, pd.Series]:
    """
    Given a Series of hour-of-day integers, returns (shift_active_flag, shift_boundary_flag).

    shift_active_flag: 1 if the hour falls within any configured shift window.
    Handles shifts that wrap past midnight (e.g. a 22:00-06:00 night shift).

    shift_boundary_flag: 1 if the hour is within one hour of a shift starting or
    ending. This is the window where simultaneous machine start-up/shutdown causes
    a real, expected surge or drop — flags.py uses this to avoid calling a normal
    shift-change spike an "anomaly."
    """
    parsed = _parse_shift_pattern(shift_pattern)
    active = pd.Series(False, index=hour_series.index)
    boundary = pd.Series(False, index=hour_series.index)

    for start_h, end_h in parsed:
        if start_h <= end_h:
            active |= hour_series.between(start_h, end_h - 1)
        else:  # overnight shift, wraps past midnight
            active |= (hour_series >= start_h) | (hour_series < end_h)
        boundary |= hour_series.isin([start_h, (start_h + 1) % 24])
        boundary |= hour_series.isin([end_h, (end_h + 1) % 24])

    return active.astype(int), boundary.astype(int)


def build_features(
    df: pd.DataFrame,
    target_col: str = "Global_active_power",
    shift_pattern=None,
) -> pd.DataFrame:
    """
    Given a dataframe with columns ['datetime', target_col], return a new
    dataframe with engineered temporal + shift + lag + rolling features.

    shift_pattern: list of (start, end) 24h-clock strings, e.g.
        [("06:00", "14:00"), ("14:00", "22:00")]
    for a two-shift MSME. Defaults to DEFAULT_SHIFT_PATTERN if not given —
    pass the company's actual pattern (from the `companies` table) once
    multi-tenancy is wired in, or accuracy silently degrades to the
    household-shaped fallback.

    Rows that can't have lag/rolling features computed (start of series)
    are dropped.
    """
    df = df.copy().sort_values("datetime").reset_index(drop=True)

    df["hour"] = df["datetime"].dt.hour
    df["day_of_week"] = df["datetime"].dt.dayofweek  # 0=Mon
    df["month"] = df["datetime"].dt.month
    df["is_weekend"] = df["day_of_week"].isin([5, 6]).astype(int)

    shift_active, shift_boundary = compute_shift_flags(df["hour"], shift_pattern)
    df["shift_active_flag"] = shift_active
    df["shift_boundary_flag"] = shift_boundary

    # lag features
    df["lag_1h"] = df[target_col].shift(1)
    df["lag_24h"] = df[target_col].shift(24)
    df["lag_168h"] = df[target_col].shift(168)  # 1 week

    # rolling stats (24h window)
    df["roll_mean_24h"] = df[target_col].rolling(24).mean()
    df["roll_std_24h"] = df[target_col].rolling(24).std()

    df = df.dropna().reset_index(drop=True)
    return df


FEATURE_COLUMNS = [
    "hour",
    "day_of_week",
    "month",
    "is_weekend",
    "shift_active_flag",
    "shift_boundary_flag",
    "lag_1h",
    "lag_24h",
    "lag_168h",
    "roll_mean_24h",
    "roll_std_24h",
]
