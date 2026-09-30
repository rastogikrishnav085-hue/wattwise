import pandas as pd
import pytest

from src.flags import TariffWindow, flag_peak_hours
from src.demand_limit import DemandLimitConfig, flag_demand_breaches, summarize_demand_risk
from src.recommendations import generate_recommendations
from src.report import build_summary_report


@pytest.fixture
def report_inputs():
    tariff = TariffWindow()
    df = pd.DataFrame({
        "datetime": pd.date_range("2024-01-01", periods=24, freq="h"),
        "forecast_kw": [1.0] * 24,
    })
    flagged = flag_peak_hours(df, tariff)
    demand_config = DemandLimitConfig(sanctioned_load_kw=10)
    demand_flagged = flag_demand_breaches(flagged, demand_config)
    demand_summary = summarize_demand_risk(demand_flagged)
    recs = generate_recommendations(
        demand_flagged, tariff, n_anomalies_forecast=0, n_anomalies_historical=0,
        demand_summary=demand_summary, demand_config=demand_config,
    )
    return tariff, demand_config, demand_summary, recs


def _base_kwargs(tariff, demand_config, demand_summary, recs):
    return dict(
        data_source="demo_synthetic_dataset", scenario="normal", tariff=tariff,
        demand_config=demand_config, demand_summary=demand_summary,
        savings_baseline=100.0, savings_optimized=90.0, savings_pct=10.0,
        monthly_savings_est=300.0, n_peak_hours=4, n_anomalies_forecast=0,
        n_anomalies_historical=0, model_mae=0.1, model_rmse=0.15,
        arima_order=(1, 1, 1), rf_weight=0.8, recommendations=recs,
    )


def test_report_is_nonempty_markdown_string(report_inputs):
    tariff, demand_config, demand_summary, recs = report_inputs
    report = build_summary_report(**_base_kwargs(tariff, demand_config, demand_summary, recs))
    assert isinstance(report, str)
    assert report.startswith("# WattWise")
    assert "Sanctioned-Load" in report


def test_report_includes_all_recommendations(report_inputs):
    tariff, demand_config, demand_summary, recs = report_inputs
    report = build_summary_report(**_base_kwargs(tariff, demand_config, demand_summary, recs))
    for rec in recs:
        assert rec.message in report


def test_report_handles_empty_recommendations(report_inputs):
    tariff, demand_config, demand_summary, _ = report_inputs
    kwargs = _base_kwargs(tariff, demand_config, demand_summary, [])
    report = build_summary_report(**kwargs)
    assert "No recommendations" in report


def test_report_omits_ci_section_when_not_given(report_inputs):
    tariff, demand_config, demand_summary, recs = report_inputs
    report = build_summary_report(**_base_kwargs(tariff, demand_config, demand_summary, recs))
    assert "confidence interval" not in report.lower()


def test_report_includes_ci_section_when_given(report_inputs):
    tariff, demand_config, demand_summary, recs = report_inputs
    kwargs = _base_kwargs(tariff, demand_config, demand_summary, recs)
    report = build_summary_report(**kwargs, forecast_ci=(108.0, 129.0, 90))
    assert "confidence interval" in report.lower()
    assert "108.0" in report and "129.0" in report


def test_report_omits_consultant_section_when_not_given(report_inputs):
    tariff, demand_config, demand_summary, recs = report_inputs
    report = build_summary_report(**_base_kwargs(tariff, demand_config, demand_summary, recs))
    assert "Consultant Notes" not in report


def test_report_includes_consultant_notes_when_given(report_inputs):
    tariff, demand_config, demand_summary, recs = report_inputs
    kwargs = _base_kwargs(tariff, demand_config, demand_summary, recs)
    notes = {
        "trending": [{"message": "Penalty exposure is rising week over week."}],
        "strategic": [{"message": "Consider a contract-demand revision."}],
    }
    report = build_summary_report(**kwargs, consultant_notes=notes)
    assert "Consultant Notes" in report
    assert "Penalty exposure is rising week over week." in report
    assert "Consider a contract-demand revision." in report


def test_report_omits_consultant_section_when_notes_are_all_empty(report_inputs):
    tariff, demand_config, demand_summary, recs = report_inputs
    kwargs = _base_kwargs(tariff, demand_config, demand_summary, recs)
    report = build_summary_report(**kwargs, consultant_notes={"trending": [], "strategic": []})
    assert "Consultant Notes" not in report
