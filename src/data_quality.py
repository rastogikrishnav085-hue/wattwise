"""
data_quality.py
-----------------
Validates a loaded consumption series BEFORE it's allowed near training.

A file that parses correctly (right columns, right types) can still be
useless to train on — mostly missing, effectively constant, full of
duplicate timestamps, wrong units (watts instead of kilowatts), or full
of gaps too large for the weekly-lag features to mean anything. A model
trained on data like this doesn't crash — it silently produces a forecast
that looks normal and is meaningless, which is worse than a visible
failure. This module exists to catch that class of problem at load time
and reject it with a specific, actionable reason.

This runs AFTER format parsing (_parse_uci_format), not instead of it —
malformed CSVs are still caught earlier as DataLoadError.
"""

from __future__ import annotations
from dataclasses import dataclass, field

import pandas as pd

MIN_ROWS = 48
MAX_MISSING_RATIO = 0.05          # >5% missing after hourly resample is suspicious
MAX_DUPLICATE_TIMESTAMPS = 0      # shouldn't exist post-resample; if present, upstream parsing is wrong
MAX_NEGATIVE_RATIO = 0.0          # negative power draw isn't physically meaningful here
MAX_EXTREME_OUTLIER_RATIO = 0.10  # >10% of points beyond 5-sigma suggests a units/scale problem
MAX_GAP_HOURS = 72                # a gap over 3 days makes the 168h (weekly) lag feature meaningless
MIN_VARIANCE = 1e-6               # effectively constant data has nothing for a model to learn


class DataQualityError(ValueError):
    """Raised when a dataset parses fine but isn't fit to train on."""


@dataclass
class QualityReport:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    n_rows: int = 0
    missing_ratio: float = 0.0
    duplicate_timestamps: int = 0
    constant_value: bool = False
    negative_ratio: float = 0.0
    extreme_outlier_ratio: float = 0.0
    gap_hours_max: float = 0.0

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "reasons": self.reasons,
            "warnings": self.warnings,
            "n_rows": self.n_rows,
            "missing_ratio": round(self.missing_ratio, 4),
            "duplicate_timestamps": self.duplicate_timestamps,
            "constant_value": self.constant_value,
            "negative_ratio": round(self.negative_ratio, 4),
            "extreme_outlier_ratio": round(self.extreme_outlier_ratio, 4),
            "gap_hours_max": round(self.gap_hours_max, 1),
        }


def assess_quality(df: pd.DataFrame, value_col: str = "Global_active_power") -> QualityReport:
    """df must have ['datetime', value_col] columns, already parsed."""
    reasons: list[str] = []
    warnings: list[str] = []

    n_rows = len(df)
    if n_rows < MIN_ROWS:
        reasons.append(f"Only {n_rows} rows — need at least {MIN_ROWS} hourly readings to assess, let alone train.")

    dup_count = int(df["datetime"].duplicated().sum()) if n_rows else 0
    if dup_count > MAX_DUPLICATE_TIMESTAMPS:
        reasons.append(f"{dup_count} duplicate timestamp(s) found — data wasn't cleanly resampled to hourly.")

    values = df[value_col] if value_col in df.columns else pd.Series(dtype=float)
    missing_ratio = float(values.isna().mean()) if n_rows else 1.0
    if missing_ratio > MAX_MISSING_RATIO:
        reasons.append(f"{missing_ratio:.1%} of readings are missing — too sparse to train a reliable model.")

    clean_values = values.dropna()
    variance = float(clean_values.var()) if len(clean_values) > 1 else 0.0
    constant_value = variance < MIN_VARIANCE
    if constant_value:
        reasons.append("Consumption values are effectively constant — there is nothing for a model to learn.")

    negative_ratio = float((clean_values < 0).mean()) if len(clean_values) else 0.0
    if negative_ratio > MAX_NEGATIVE_RATIO:
        reasons.append(f"{negative_ratio:.1%} of readings are negative — not physically meaningful power draw.")

    extreme_ratio = 0.0
    if len(clean_values) > 10 and not constant_value:
        # Median + MAD (median absolute deviation) instead of mean/std: mean and std
        # are themselves dragged by the outliers when a sizable chunk of the series
        # is at a different scale (e.g. 15% of readings at 5000 instead of ~0.5) —
        # that inflates std enough that the "outliers" no longer look extreme
        # relative to their own distorted statistics ("masking"). Median/MAD stay
        # anchored to the bulk of normal-scale readings instead.
        # Compared against the typical level for the SAME hour of day, not one global median:
        # a shift-based factory legitimately runs at a high level for its shift hours and
        # idles otherwise, and against a single global median every working-hour reading
        # looked like an "extreme outlier" (a valid MSME export was being rejected).
        if "datetime" in df.columns:
            hours = pd.to_datetime(df.loc[clean_values.index, "datetime"]).dt.hour
            median = clean_values.groupby(hours).transform("median")
            dev = (clean_values - median).abs()
            mad = dev.groupby(hours).transform("median")
        else:
            dev = (clean_values - clean_values.median()).abs()
            mad = pd.Series(dev.median(), index=clean_values.index)
        usable = mad > 0
        if usable.any():
            modified_z = 0.6745 * dev[usable] / mad[usable]
            extreme_ratio = float((modified_z > 3.5).sum() / len(clean_values))
        if extreme_ratio > MAX_EXTREME_OUTLIER_RATIO:
            reasons.append(
                f"{extreme_ratio:.1%} of readings are extreme outliers (robust modified z-score > 3.5) — "
                "check the units (e.g. watts instead of kilowatts) or the sensor/export before trusting this file."
            )

    gap_hours_max = 0.0
    if n_rows > 1:
        gaps = df["datetime"].sort_values().diff().dropna()
        if len(gaps):
            gap_hours_max = float(gaps.max().total_seconds() / 3600)
            if gap_hours_max > MAX_GAP_HOURS:
                reasons.append(
                    f"Largest gap in the series is {gap_hours_max:.0f} hours, over the {MAX_GAP_HOURS}-hour "
                    "limit — the weekly-lag feature this pipeline relies on won't be meaningful across a gap that size."
                )

    if 0 < missing_ratio <= MAX_MISSING_RATIO:
        warnings.append(f"{missing_ratio:.1%} of readings were missing (within tolerance, filled by resampling).")
    if n_rows and n_rows < 24 * 14:
        warnings.append(
            f"Only {n_rows} hours (~{n_rows / 24:.1f} days) of history — a few weeks gives the model "
            "more to learn a weekly pattern from; accuracy on a shorter series will be less reliable."
        )

    return QualityReport(
        passed=(len(reasons) == 0),
        reasons=reasons,
        warnings=warnings,
        n_rows=n_rows,
        missing_ratio=missing_ratio,
        duplicate_timestamps=dup_count,
        constant_value=constant_value,
        negative_ratio=negative_ratio,
        extreme_outlier_ratio=extreme_ratio,
        gap_hours_max=gap_hours_max,
    )


def validate_or_raise(df: pd.DataFrame, value_col: str = "Global_active_power", label: str = "dataset") -> QualityReport:
    """Raises DataQualityError with every specific reason if the dataset fails; otherwise
    returns the report (which may still carry non-fatal warnings) so the caller can log
    or surface them without blocking."""
    report = assess_quality(df, value_col=value_col)
    if not report.passed:
        raise DataQualityError(f"{label} failed data quality checks:\n- " + "\n- ".join(report.reasons))
    return report
