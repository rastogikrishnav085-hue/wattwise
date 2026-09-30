import pandas as pd
import pytest

from src.flags import TariffWindow, flag_peak_hours
from src.savings import calculate_savings


@pytest.fixture
def flagged_24h():
    tariff = TariffWindow()
    df = pd.DataFrame({
        "datetime": pd.date_range("2024-01-01", periods=24, freq="h"),
        "forecast_kw": [1.0] * 24,
    })
    return flag_peak_hours(df, tariff), tariff


def test_zero_shift_means_zero_savings(flagged_24h):
    flagged, tariff = flagged_24h
    result = calculate_savings(flagged, tariff, shift_fraction=0.0)
    assert result.savings_amount == pytest.approx(0.0, abs=1e-6)
    assert result.baseline_cost == pytest.approx(result.optimized_cost, abs=1e-6)


def test_higher_shift_fraction_saves_more(flagged_24h):
    flagged, tariff = flagged_24h
    low = calculate_savings(flagged, tariff, shift_fraction=0.1)
    high = calculate_savings(flagged, tariff, shift_fraction=0.5)
    assert high.savings_amount > low.savings_amount


def test_savings_never_exceed_baseline_cost(flagged_24h):
    flagged, tariff = flagged_24h
    result = calculate_savings(flagged, tariff, shift_fraction=1.0)
    assert result.optimized_cost >= 0
    assert result.optimized_cost <= result.baseline_cost


def test_rejects_out_of_range_shift_fraction(flagged_24h):
    flagged, tariff = flagged_24h
    with pytest.raises(ValueError):
        calculate_savings(flagged, tariff, shift_fraction=1.5)


def test_rejects_missing_columns():
    tariff = TariffWindow()
    bare_df = pd.DataFrame({"forecast_kw": [1.0, 2.0]})
    with pytest.raises(ValueError):
        calculate_savings(bare_df, tariff)


def test_monthly_savings_scales_by_horizon_not_a_flat_x30():
    tariff = TariffWindow()
    one_day = flag_peak_hours(pd.DataFrame({
        "datetime": pd.date_range("2024-01-01", periods=24, freq="h"), "forecast_kw": [10.0] * 24}), tariff)
    week = flag_peak_hours(pd.DataFrame({
        "datetime": pd.date_range("2024-01-01", periods=168, freq="h"), "forecast_kw": [10.0] * 168}), tariff)
    m_day = calculate_savings(one_day, tariff).monthly_savings
    m_week = calculate_savings(week, tariff).monthly_savings
    assert m_day == pytest.approx(m_week)  # same load every hour -> same monthly figure
