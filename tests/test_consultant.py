import os
import tempfile

import pytest

from src import database as db
from src import consultant


@pytest.fixture
def company(temp_db):
    record = db.CompanyRecord(name="Test Factory", tier="small", sanctioned_load_kw=100.0)
    company_id, _ = db.create_company(record, db_path=temp_db)
    return company_id


def _save_run(company_id, db_path, *, penalty, anomalies, breach_hours):
    db.save_forecast_run(
        company_id=company_id, source="api", data_source="demo_synthetic_dataset", horizon_hours=24,
        peak_hours_flagged=1, anomalies_forecast=anomalies, anomalies_historical=0,
        demand_breach_hours=breach_hours, demand_warning_hours=0, estimated_penalty=penalty,
        baseline_cost=10.0, optimized_cost=9.0, savings_pct=10.0,
        monthly_savings_est=30.0, model_mae_kw=0.1, recommendations=[], db_path=db_path,
    )


def test_no_trending_notes_before_minimum_run_count(temp_db, company):
    _save_run(company, temp_db, penalty=100, anomalies=0, breach_hours=0)
    _save_run(company, temp_db, penalty=200, anomalies=0, breach_hours=0)
    notes = consultant.generate_trending_notes(company, db_path=temp_db)
    assert notes == []


def test_trending_note_fires_on_rising_penalty(temp_db, company):
    for penalty in (100, 200, 300, 500):
        _save_run(company, temp_db, penalty=penalty, anomalies=0, breach_hours=0)
    notes = consultant.generate_trending_notes(company, db_path=temp_db)
    assert any(n["trend_direction"] == "rising" for n in notes)


def test_trending_note_fires_on_falling_anomaly_count(temp_db, company):
    for anomalies in (10, 8, 4, 1):
        _save_run(company, temp_db, penalty=100, anomalies=anomalies, breach_hours=0)
    notes = consultant.generate_trending_notes(company, db_path=temp_db)
    assert any(n["trend_direction"] == "falling" for n in notes)


def test_no_trending_note_when_flat(temp_db, company):
    for _ in range(4):
        _save_run(company, temp_db, penalty=100, anomalies=0, breach_hours=0)
    notes = consultant.generate_trending_notes(company, db_path=temp_db)
    assert notes == []


def test_strategic_note_fires_on_high_breach_frequency(temp_db, company):
    for i in range(10):
        _save_run(company, temp_db, penalty=100, anomalies=0, breach_hours=1 if i % 2 == 0 else 0)
    notes = consultant.generate_strategic_notes(company, db_path=temp_db)
    assert len(notes) == 1
    assert "sanctioned-load breach" in notes[0]["message"]


def test_no_strategic_note_below_breach_threshold(temp_db, company):
    for i in range(10):
        _save_run(company, temp_db, penalty=100, anomalies=0, breach_hours=1 if i == 0 else 0)
    notes = consultant.generate_strategic_notes(company, db_path=temp_db)
    assert notes == []


def test_run_consultant_returns_both_tiers(temp_db, company):
    for penalty in (100, 200, 300, 500):
        _save_run(company, temp_db, penalty=penalty, anomalies=0, breach_hours=0)
    result = consultant.run_consultant(company, db_path=temp_db)
    assert "trending" in result
    assert "strategic" in result


def test_notes_are_persisted_to_consultant_notes_table(temp_db, company):
    for penalty in (100, 200, 300, 500):
        _save_run(company, temp_db, penalty=penalty, anomalies=0, breach_hours=0)
    consultant.generate_trending_notes(company, db_path=temp_db)
    saved = db.get_consultant_notes(company, tier="trending", db_path=temp_db)
    assert len(saved) >= 1
