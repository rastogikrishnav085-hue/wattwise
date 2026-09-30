import pandas as pd
import pytest

from src.flags import TariffWindow, flag_peak_hours
from src.demand_limit import DemandLimitConfig, flag_demand_breaches, summarize_demand_risk
from src.recommendations import generate_recommendations, Category, Severity


@pytest.fixture
def base_flagged():
    tariff = TariffWindow()
    df = pd.DataFrame({
        "datetime": pd.date_range("2024-01-01", periods=24, freq="h"),
        "forecast_kw": [1.0] * 24,
    })
    return flag_peak_hours(df, tariff), tariff


def test_always_includes_load_shift_recommendations(base_flagged):
    flagged, tariff = base_flagged
    recs = generate_recommendations(flagged, tariff, n_anomalies_forecast=0, n_anomalies_historical=0)
    categories = {r.category for r in recs}
    assert Category.LOAD_SHIFT in categories


def test_no_demand_recommendation_without_demand_config(base_flagged):
    flagged, tariff = base_flagged
    recs = generate_recommendations(flagged, tariff, n_anomalies_forecast=0, n_anomalies_historical=0)
    assert not any(r.category == Category.DEMAND_LIMIT for r in recs)


def test_breach_produces_critical_demand_recommendation_first():
    tariff = TariffWindow()
    df = pd.DataFrame({
        "datetime": pd.date_range("2024-01-01", periods=24, freq="h"),
        "forecast_kw": [1.0] * 24,
    })
    flagged = flag_peak_hours(df, tariff)
    config = DemandLimitConfig(sanctioned_load_kw=0.5)  # every hour breaches
    demand_flagged = flag_demand_breaches(flagged, config)
    summary = summarize_demand_risk(demand_flagged)

    recs = generate_recommendations(
        demand_flagged, tariff, n_anomalies_forecast=0, n_anomalies_historical=0,
        demand_summary=summary, demand_config=config,
    )
    assert recs[0].category == Category.DEMAND_LIMIT
    assert recs[0].severity == Severity.CRITICAL
    assert recs[0].automatable is False


def test_anomaly_recommendations_appear_when_flagged(base_flagged):
    flagged, tariff = base_flagged
    recs = generate_recommendations(flagged, tariff, n_anomalies_forecast=2, n_anomalies_historical=5)
    anomaly_recs = [r for r in recs if r.category == Category.ANOMALY]
    assert len(anomaly_recs) == 2


def test_recommendations_sorted_by_severity(base_flagged):
    flagged, tariff = base_flagged
    recs = generate_recommendations(flagged, tariff, n_anomalies_forecast=1, n_anomalies_historical=1)
    severities = [r.severity for r in recs]
    order = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2}
    assert severities == sorted(severities, key=lambda s: order[s])


def test_load_shift_recommendations_are_marked_automatable(base_flagged):
    flagged, tariff = base_flagged
    recs = generate_recommendations(flagged, tariff, n_anomalies_forecast=0, n_anomalies_historical=0)
    load_shift_recs = [r for r in recs if r.category == Category.LOAD_SHIFT]
    assert all(r.automatable for r in load_shift_recs)


def test_industry_type_gives_factory_advice_not_household_advice(base_flagged):
    flagged, tariff = base_flagged
    recs = generate_recommendations(flagged, tariff, 0, 0, industry_type="textile")
    text = " ".join(r.message for r in recs).lower()
    assert "loom" in text
    assert "washing machine" not in text and "ev" not in text.split()


def test_unknown_industry_falls_back_to_generic(base_flagged):
    flagged, tariff = base_flagged
    recs = generate_recommendations(flagged, tariff, 0, 0, industry_type="not-a-real-industry")
    assert any(r.category == Category.LOAD_SHIFT for r in recs)
