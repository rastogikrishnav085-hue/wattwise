import io

import pandas as pd
import pytest

from src.flags import TariffWindow
from src.demand_limit import DemandLimitConfig, DemandSummary
from src.recommendations import Recommendation, Category, Severity
from src.pdf_report import build_pdf_report


@pytest.fixture
def base_kwargs():
    return dict(
        data_source="demo_synthetic_dataset", scenario="normal", tariff=TariffWindow(),
        demand_config=DemandLimitConfig(sanctioned_load_kw=500),
        demand_summary=DemandSummary(breach_hours=1, warning_hours=0, peak_forecast_kw=520.0,
                                      total_estimated_penalty=3000.0, first_breach_time=pd.Timestamp("2024-01-01 19:00")),
        savings_baseline=1000.0, savings_optimized=900.0, savings_pct=10.0, monthly_savings_est=3000.0,
        n_peak_hours=4, n_anomalies_forecast=1, n_anomalies_historical=3,
        model_mae=0.15, model_rmse=0.2, arima_order=(1, 1, 1), rf_weight=0.8,
        predicted_peak_kw=520.0, predicted_peak_time="Mon 19:00",
        predicted_avg_kw=300.0, predicted_total_kwh=7200.0,
    )


def test_pdf_bytes_start_with_pdf_magic_number(base_kwargs):
    pdf_bytes = build_pdf_report(recommendations=[
        Recommendation(Category.LOAD_SHIFT, Severity.INFO, "Shift load.", True),
    ], **base_kwargs)
    assert pdf_bytes[:5] == b"%PDF-"


def test_pdf_handles_empty_recommendations(base_kwargs):
    pdf_bytes = build_pdf_report(recommendations=[], **base_kwargs)
    assert pdf_bytes[:5] == b"%PDF-"
    assert len(pdf_bytes) > 500


def test_pdf_handles_long_recommendation_text_without_crashing(base_kwargs):
    long_msg = "This is a deliberately long recommendation message. " * 20
    pdf_bytes = build_pdf_report(recommendations=[
        Recommendation(Category.DEMAND_LIMIT, Severity.CRITICAL, long_msg, False),
    ], **base_kwargs)
    assert pdf_bytes[:5] == b"%PDF-"


def test_pdf_handles_many_recommendations_without_crashing(base_kwargs):
    recs = [
        Recommendation(Category.LOAD_SHIFT, Severity.INFO, f"Recommendation number {i}.", i % 2 == 0)
        for i in range(30)
    ]
    pdf_bytes = build_pdf_report(recommendations=recs, **base_kwargs)
    assert pdf_bytes[:5] == b"%PDF-"


def test_pdf_content_contains_key_figures(base_kwargs):
    from pypdf import PdfReader
    pdf_bytes = build_pdf_report(recommendations=[
        Recommendation(Category.LOAD_SHIFT, Severity.INFO, "Shift load.", True),
    ], **base_kwargs)
    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "".join(page.extract_text() for page in reader.pages)
    assert "WattWise" in text
    assert "520.00 kW" in text  # predicted peak
    assert "Shift load." in text


def test_pdf_includes_confidence_interval_when_given(base_kwargs):
    from pypdf import PdfReader
    pdf_bytes = build_pdf_report(
        recommendations=[Recommendation(Category.LOAD_SHIFT, Severity.INFO, "Shift load.", True)],
        forecast_ci=(480.0, 560.0, 90),
        **base_kwargs,
    )
    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "".join(page.extract_text() for page in reader.pages)
    assert "480.00" in text and "560.00" in text
    assert "90" in text


def test_pdf_includes_consultant_notes_when_given(base_kwargs):
    from pypdf import PdfReader
    notes = {
        "trending": [{"message": "Penalty exposure is rising."}],
        "strategic": [{"message": "Consider a contract-demand revision."}],
    }
    pdf_bytes = build_pdf_report(
        recommendations=[Recommendation(Category.LOAD_SHIFT, Severity.INFO, "Shift load.", True)],
        consultant_notes=notes,
        **base_kwargs,
    )
    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "".join(page.extract_text() for page in reader.pages)
    assert "Consultant Notes" in text
    assert "Penalty exposure is rising." in text
    assert "Consider a contract-demand revision." in text


def test_pdf_omits_consultant_section_when_not_given(base_kwargs):
    from pypdf import PdfReader
    pdf_bytes = build_pdf_report(
        recommendations=[Recommendation(Category.LOAD_SHIFT, Severity.INFO, "Shift load.", True)],
        **base_kwargs,
    )
    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "".join(page.extract_text() for page in reader.pages)
    assert "Consultant Notes" not in text
