import pandas as pd
import pytest

from src.demand_limit import (
    DemandLimitConfig,
    InvalidDemandLimitError,
    flag_demand_breaches,
    summarize_demand_risk,
)


def test_rejects_non_positive_sanctioned_load():
    with pytest.raises(InvalidDemandLimitError):
        DemandLimitConfig(sanctioned_load_kw=0)


def test_rejects_negative_penalty_rate():
    with pytest.raises(InvalidDemandLimitError):
        DemandLimitConfig(sanctioned_load_kw=100, penalty_rate_per_kw=-5)


def test_rejects_invalid_warning_margin():
    with pytest.raises(InvalidDemandLimitError):
        DemandLimitConfig(sanctioned_load_kw=100, warning_margin_pct=150)


def test_warning_threshold_computed_correctly():
    config = DemandLimitConfig(sanctioned_load_kw=100, warning_margin_pct=10)
    assert config.warning_threshold_kw == pytest.approx(90.0)


def test_flag_demand_breaches_marks_status_correctly():
    config = DemandLimitConfig(sanctioned_load_kw=100, warning_margin_pct=10, penalty_rate_per_kw=150)
    df = pd.DataFrame({
        "datetime": pd.date_range("2024-01-01", periods=3, freq="h"),
        "forecast_kw": [80.0, 95.0, 110.0],  # normal, warning, breach
    })
    flagged = flag_demand_breaches(df, config)
    assert list(flagged["demand_status"]) == ["Normal", "Warning", "Breach"]
    assert flagged["excess_kw"].iloc[2] == pytest.approx(10.0)
    assert flagged["estimated_penalty"].iloc[2] == pytest.approx(1500.0)
    assert flagged["excess_kw"].iloc[0] == 0
    assert flagged["estimated_penalty"].iloc[0] == 0


def test_summarize_demand_risk_counts_correctly():
    config = DemandLimitConfig(sanctioned_load_kw=100, warning_margin_pct=10, penalty_rate_per_kw=150)
    df = pd.DataFrame({
        "datetime": pd.date_range("2024-01-01", periods=4, freq="h"),
        "forecast_kw": [80.0, 95.0, 110.0, 120.0],
    })
    flagged = flag_demand_breaches(df, config)
    summary = summarize_demand_risk(flagged)
    assert summary.breach_hours == 2
    assert summary.warning_hours == 1
    assert summary.peak_forecast_kw == pytest.approx(120.0)
    assert summary.total_estimated_penalty == pytest.approx((10 + 20) * 150)
    assert summary.first_breach_time == df["datetime"].iloc[2]


def test_summarize_demand_risk_no_breach_gives_none_timestamp():
    config = DemandLimitConfig(sanctioned_load_kw=1000)
    df = pd.DataFrame({
        "datetime": pd.date_range("2024-01-01", periods=3, freq="h"),
        "forecast_kw": [1.0, 2.0, 3.0],
    })
    flagged = flag_demand_breaches(df, config)
    summary = summarize_demand_risk(flagged)
    assert summary.breach_hours == 0
    assert summary.first_breach_time is None
