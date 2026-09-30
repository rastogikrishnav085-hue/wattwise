from src.whatts_on import WhattsOnContext, answer


def context():
    return WhattsOnContext(
        company_name="Demo MSME", industry="textile", sanctioned_load_kw=100,
        forecast_peak_kw=108, forecast_avg_kw=72, breach_hours=2, warning_hours=1,
        estimated_penalty=1200, baseline_cost=10000, optimized_cost=8500,
        savings_pct=15, monthly_savings=4500, forecast_anomalies=2,
        historical_anomalies=4, mae_kw=3.2, rmse_kw=4.8, rf_weight=1.0,
        arima_weight=0.0, data_source="uploaded_dataset", horizon_hours=24,
        recommendations=["Stagger machine start-ups."],
        consultant_notes=["Penalty exposure is rising across recent runs."],
    )


def test_whatts_on_explains_sanctioned_load():
    text = answer("Will I exceed my sanctioned load?", context())
    assert "2 forecast hour" in text
    assert "₹1,200" in text


def test_whatts_on_explains_savings():
    text = answer("How much can I save by shifting production?", context())
    assert "₹4,500" in text
    assert "15.0%" in text


def test_whatts_on_explains_accuracy():
    text = answer("What is the model accuracy?", context())
    assert "MAE 3.20 kW" in text
    assert "RMSE 4.80 kW" in text
    assert "100% Random Forest" in text


def test_whatts_on_explains_anomalies():
    text = answer("Do I have any anomalies?", context())
    assert "2 forecast anomaly" in text
    assert "4 historical anomaly" in text


def test_whatts_on_unknown_question_is_safe():
    text = answer("Tell me something unrelated", context())
    assert "forecast" in text.lower()


def test_whatts_on_data_source_answer():
    text = answer("What data are you using?", context())
    assert "uploaded dataset" in text.lower()


def test_whatts_on_gemini_disabled_falls_back(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("WATTWISE_USE_GEMINI", "false")
    text = answer("What is the model accuracy?", context())
    assert "MAE 3.20 kW" in text
