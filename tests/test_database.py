import os
import tempfile

import pytest

from src import database as db


@pytest.fixture
def company(temp_db):
    record = db.CompanyRecord(
        name="Test Factory", tier="small", sanctioned_load_kw=100.0,
        industry_type="textile", connection_type="LT",
    )
    company_id, raw_key = db.create_company(record, db_path=temp_db)
    return company_id, raw_key


def test_init_db_creates_all_tables(temp_db):
    """Backend-agnostic: checks the schema exists, not that a file does (there is no
    file when the backend is Postgres)."""
    from sqlalchemy import inspect
    db.init_db(db_path=temp_db)
    tables = set(inspect(db._resolve_engine(temp_db)).get_table_names())
    assert {"companies", "users", "training_runs", "forecast_runs",
            "recommendations_log", "consultant_notes", "audit_log"} <= tables


def test_create_company_rejects_invalid_tier(temp_db):
    record = db.CompanyRecord(name="Bad Tier Co", tier="huge", sanctioned_load_kw=100.0)
    with pytest.raises(ValueError):
        db.create_company(record, db_path=temp_db)


def test_create_company_rejects_non_positive_sanctioned_load(temp_db):
    record = db.CompanyRecord(name="Bad Load Co", tier="micro", sanctioned_load_kw=0)
    with pytest.raises(ValueError):
        db.create_company(record, db_path=temp_db)


def test_create_company_returns_id_and_raw_key(company):
    company_id, raw_key = company
    assert company_id == 1
    assert raw_key.startswith("wwk_")


def test_get_company_by_api_key_resolves_correct_company(temp_db, company):
    company_id, raw_key = company
    found = db.get_company_by_api_key(raw_key, db_path=temp_db)
    assert found["id"] == company_id
    assert found["name"] == "Test Factory"


def test_api_key_lookup_tolerates_pasted_whitespace_and_quotes(temp_db, company):
    company_id, raw_key = company
    for messy in (raw_key + " ", " " + raw_key, raw_key + "\n", f'"{raw_key}"', f"'{raw_key}' "):
        found = db.get_company_by_api_key(messy, db_path=temp_db)
        assert found is not None and found["id"] == company_id
    assert db.get_company_by_api_key("   ", db_path=temp_db) is None
    assert db.get_company_by_api_key("", db_path=temp_db) is None


def test_get_company_by_wrong_key_returns_none(temp_db, company):
    assert db.get_company_by_api_key("wwk_not_a_real_key", db_path=temp_db) is None


def test_rotate_api_key_invalidates_old_key_and_issues_new_one(temp_db, company):
    company_id, old_key = company
    new_key = db.rotate_api_key(company_id, db_path=temp_db)
    assert new_key != old_key
    assert db.get_company_by_api_key(old_key, db_path=temp_db) is None
    resolved = db.get_company_by_api_key(new_key, db_path=temp_db)
    assert resolved["id"] == company_id


def test_create_user_and_verify_password(temp_db, company):
    company_id, _ = company
    user_id = db.create_user(company_id, "owner@test.com", "correct-horse-battery", db_path=temp_db)
    user = db.get_user_by_email("owner@test.com", db_path=temp_db)
    assert user["id"] == user_id
    assert user["company_id"] == company_id
    assert db.verify_password("correct-horse-battery", user["password_hash"], user["password_salt"])
    assert not db.verify_password("wrong-password", user["password_hash"], user["password_salt"])


def test_create_user_rejects_invalid_role(temp_db, company):
    company_id, _ = company
    with pytest.raises(ValueError):
        db.create_user(company_id, "bad@test.com", "password123", role="superadmin", db_path=temp_db)


def test_save_and_read_training_run(temp_db, company):
    company_id, _ = company
    run_id = db.save_training_run(
        company_id=company_id, data_source="demo_synthetic_dataset", mae_kw=0.1, rmse_kw=0.15,
        arima_order=(1, 1, 1), rf_weight=0.8, arima_weight=0.2,
        scenario="normal", db_path=temp_db,
    )
    assert run_id == 1
    runs = db.get_recent_training_runs(company_id, db_path=temp_db)
    assert len(runs) == 1
    assert runs[0]["mae_kw"] == 0.1
    assert runs[0]["scenario"] == "normal"


def test_save_and_read_forecast_run_with_recommendations(temp_db, company):
    company_id, _ = company
    recs = [
        db.RecommendationRecord(category="demand_limit", severity="critical", message="Breach!", automatable=False),
        db.RecommendationRecord(category="load_shift", severity="info", message="Shift load.", automatable=True),
    ]
    run_id = db.save_forecast_run(
        company_id=company_id, source="dashboard", data_source="demo_synthetic_dataset", horizon_hours=24,
        peak_hours_flagged=4, anomalies_forecast=1, anomalies_historical=2,
        demand_breach_hours=1, demand_warning_hours=0, estimated_penalty=500.0,
        baseline_cost=100.0, optimized_cost=90.0, savings_pct=10.0,
        monthly_savings_est=300.0, model_mae_kw=0.1,
        recommendations=recs, scenario="high_demand", profile="MSME",
        db_path=temp_db,
    )
    runs = db.get_recent_forecast_runs(company_id, db_path=temp_db)
    assert len(runs) == 1
    assert runs[0]["id"] == run_id
    assert runs[0]["scenario"] == "high_demand"
    assert runs[0]["demand_breach_hours"] == 1

    saved_recs = db.get_recommendations_for_run(run_id, company_id, db_path=temp_db)
    assert len(saved_recs) == 2
    assert saved_recs[0]["message"] == "Breach!"
    assert saved_recs[0]["automatable"] == 0
    assert saved_recs[1]["automatable"] == 1


def test_recent_forecast_runs_respects_limit(temp_db, company):
    company_id, _ = company
    for _ in range(5):
        db.save_forecast_run(
            company_id=company_id, source="api", data_source="demo_synthetic_dataset", horizon_hours=24,
            peak_hours_flagged=1, anomalies_forecast=0, anomalies_historical=0,
            demand_breach_hours=0, demand_warning_hours=0, estimated_penalty=0.0,
            baseline_cost=10.0, optimized_cost=9.0, savings_pct=10.0,
            monthly_savings_est=30.0, model_mae_kw=0.1, recommendations=[],
            db_path=temp_db,
        )
    runs = db.get_recent_forecast_runs(company_id, limit=3, db_path=temp_db)
    assert len(runs) == 3


def test_recent_forecast_runs_ordered_newest_first(temp_db, company):
    company_id, _ = company
    ids = []
    for _ in range(3):
        run_id = db.save_forecast_run(
            company_id=company_id, source="api", data_source="demo_synthetic_dataset", horizon_hours=24,
            peak_hours_flagged=1, anomalies_forecast=0, anomalies_historical=0,
            demand_breach_hours=0, demand_warning_hours=0, estimated_penalty=0.0,
            baseline_cost=10.0, optimized_cost=9.0, savings_pct=10.0,
            monthly_savings_est=30.0, model_mae_kw=0.1, recommendations=[],
            db_path=temp_db,
        )
        ids.append(run_id)
    runs = db.get_recent_forecast_runs(company_id, db_path=temp_db)
    assert [r["id"] for r in runs] == list(reversed(ids))


# --- Tenant isolation tests — the core new guarantee in this version ---

def test_forecast_runs_not_visible_to_a_different_company(temp_db, company):
    company_id, _ = company
    other_id, _ = db.create_company(
        db.CompanyRecord(name="Other Factory", tier="micro", sanctioned_load_kw=20.0), db_path=temp_db,
    )
    db.save_forecast_run(
        company_id=company_id, source="api", data_source="demo_synthetic_dataset", horizon_hours=24,
        peak_hours_flagged=1, anomalies_forecast=0, anomalies_historical=0,
        demand_breach_hours=0, demand_warning_hours=0, estimated_penalty=0.0,
        baseline_cost=10.0, optimized_cost=9.0, savings_pct=10.0,
        monthly_savings_est=30.0, model_mae_kw=0.1, recommendations=[], db_path=temp_db,
    )
    assert db.get_recent_forecast_runs(other_id, db_path=temp_db) == []


def test_recommendations_not_readable_via_another_companys_context(temp_db, company):
    """Even with the correct forecast_run_id, a different company_id must get nothing back —
    this is the fix for the old single-tenant get_recommendations_for_run()."""
    company_id, _ = company
    other_id, _ = db.create_company(
        db.CompanyRecord(name="Other Factory", tier="micro", sanctioned_load_kw=20.0), db_path=temp_db,
    )
    run_id = db.save_forecast_run(
        company_id=company_id, source="api", data_source="demo_synthetic_dataset", horizon_hours=24,
        peak_hours_flagged=1, anomalies_forecast=0, anomalies_historical=0,
        demand_breach_hours=0, demand_warning_hours=0, estimated_penalty=0.0,
        baseline_cost=10.0, optimized_cost=9.0, savings_pct=10.0,
        monthly_savings_est=30.0, model_mae_kw=0.1,
        recommendations=[db.RecommendationRecord("general", "info", "secret", False)],
        db_path=temp_db,
    )
    assert db.get_recommendations_for_run(run_id, other_id, db_path=temp_db) == []
    # sanity check: the rightful owner still gets it
    assert len(db.get_recommendations_for_run(run_id, company_id, db_path=temp_db)) == 1


def test_clear_company_data_only_clears_that_company(temp_db, company):
    company_id, _ = company
    other_id, _ = db.create_company(
        db.CompanyRecord(name="Other Factory", tier="micro", sanctioned_load_kw=20.0), db_path=temp_db,
    )
    db.save_training_run(
        company_id=company_id, data_source="demo_synthetic_dataset", mae_kw=0.1, rmse_kw=0.15,
        arima_order=(1, 1, 1), rf_weight=0.8, arima_weight=0.2, db_path=temp_db,
    )
    db.save_training_run(
        company_id=other_id, data_source="demo_synthetic_dataset", mae_kw=0.2, rmse_kw=0.25,
        arima_order=(1, 1, 1), rf_weight=0.7, arima_weight=0.3, db_path=temp_db,
    )
    db.clear_company_data(company_id, db_path=temp_db)
    assert db.get_recent_training_runs(company_id, db_path=temp_db) == []
    assert len(db.get_recent_training_runs(other_id, db_path=temp_db)) == 1


# --- Consultant notes ---

def test_consultant_notes_saved_and_scoped_per_company(temp_db, company):
    company_id, _ = company
    note_id = db.save_consultant_note(
        company_id, tier="trending", category="anomaly",
        message="Test note.", trend_direction="rising", db_path=temp_db,
    )
    notes = db.get_consultant_notes(company_id, db_path=temp_db)
    assert len(notes) == 1
    assert notes[0]["id"] == note_id
    assert notes[0]["trend_direction"] == "rising"


def test_consultant_notes_rejects_invalid_tier(temp_db, company):
    company_id, _ = company
    with pytest.raises(ValueError):
        db.save_consultant_note(company_id, tier="urgent", category="anomaly", message="x", db_path=temp_db)


def test_consultant_notes_filtered_by_tier(temp_db, company):
    company_id, _ = company
    db.save_consultant_note(company_id, tier="trending", category="anomaly", message="a", db_path=temp_db)
    db.save_consultant_note(company_id, tier="strategic", category="demand_limit", message="b", db_path=temp_db)
    strategic_only = db.get_consultant_notes(company_id, tier="strategic", db_path=temp_db)
    assert len(strategic_only) == 1
    assert strategic_only[0]["message"] == "b"


# --- Audit log ---

def test_audit_log_records_events(temp_db, company):
    company_id, _ = company
    db.log_audit_event(company_id, action="train_triggered", detail={"scenario": "normal"}, db_path=temp_db)
    entries = db.get_audit_log(company_id, db_path=temp_db)
    assert len(entries) == 1
    assert entries[0]["action"] == "train_triggered"


def test_get_recommendations_for_nonexistent_run_returns_empty(temp_db, company):
    company_id, _ = company
    db.init_db(db_path=temp_db)
    assert db.get_recommendations_for_run(9999, company_id, db_path=temp_db) == []
