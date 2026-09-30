"""
api.py
-------
WattWise FastAPI service.

Every route that touches company data depends on security.require_company,
so authentication and tenant scoping happen the same way on every route
rather than being re-implemented per endpoint. Models are trained and
persisted per company (models/company_{id}/) — see forecast.py's
train_ensemble docstring for why that matters.
"""

from __future__ import annotations
import json
import os
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Request, UploadFile, File, Query
from pydantic import BaseModel, Field

from src import database as db
from src import consultant
from src.config import MODEL_DIR
from src.data_loader import load_consumption_data, load_from_upload, DataLoadError, LoadResult, SCENARIOS
from src.forecast import train_ensemble, forecast_next_n_hours, InsufficientDataError
from src.flags import TariffWindow, flag_peak_hours, detect_anomalies, detect_rolling_anomalies
from src.demand_limit import DemandLimitConfig, flag_demand_breaches, summarize_demand_risk
from src.savings import calculate_savings
from src.recommendations import generate_recommendations
from src.whatts_on import answer as whatts_on_answer, context_from_api_summary
from src.security import (
    require_company, CompanyContext, enforce_train_rate_limit,
    enforce_forecast_rate_limit, enforce_signup_rate_limit,
)
from src.logging_setup import get_logger

log = get_logger(__name__)

app = FastAPI(title="WattWise API", version="2.0.0")
db.init_db()


# --- Request/response schemas ---

class CompanySignupRequest(BaseModel):
    name: str
    tier: str
    sanctioned_load_kw: float
    industry_type: Optional[str] = None
    connection_type: Optional[str] = None
    shift_pattern: Optional[list[tuple[str, str]]] = None


class TrainRequest(BaseModel):
    scenario: str = Field(default="msme_shift", description=f"One of: {', '.join(SCENARIOS)}")


class WhattsOnRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


class ForecastRequest(BaseModel):
    horizon_hours: int = Field(default=24, ge=1, le=8760, description="1 hour to 1 year")
    shift_fraction: float = Field(default=0.3, ge=0.0, le=1.0)
    ci_level: float = Field(default=0.9, gt=0.0, lt=1.0)
    scenario: str = Field(default="msme_shift", description=f"One of: {', '.join(SCENARIOS)}")


# --- Helpers ---

def _company_shift_pattern(company_record: dict):
    raw = company_record.get("shift_pattern_json")
    return json.loads(raw) if raw else None


def _company_model_dir(company_id: int) -> str:
    return os.path.join(MODEL_DIR, f"company_{company_id}")


def _validate_scenario(scenario: str) -> None:
    if scenario not in SCENARIOS:
        raise HTTPException(status_code=422, detail=f"scenario must be one of {SCENARIOS}, got '{scenario}'.")


def _run_pipeline(
    company_id: int,
    load_result: LoadResult,
    shift_pattern,
    sanctioned_load: float,
    horizon_hours: int,
    shift_fraction: float,
    ci_level: float,
    source: str,
    scenario: Optional[str],
    profile: Optional[str],
    industry_type: Optional[str] = None,
) -> dict:
    train_result = train_ensemble(
        load_result.df, shift_pattern=shift_pattern, model_dir=_company_model_dir(company_id),
    )
    future = forecast_next_n_hours(load_result.df, train_result, hours=horizon_hours, ci_level=ci_level)

    tariff = TariffWindow()
    flagged = flag_peak_hours(future, tariff)
    flagged = detect_anomalies(flagged, shift_pattern=shift_pattern)
    hist_anomalies = detect_rolling_anomalies(load_result.df, shift_pattern=shift_pattern)
    n_anomalies_historical = int(hist_anomalies["is_anomaly"].sum())

    demand_config = DemandLimitConfig(sanctioned_load_kw=sanctioned_load or 100.0)
    demand_flagged = flag_demand_breaches(flagged, demand_config)
    demand_summary = summarize_demand_risk(demand_flagged)

    savings = calculate_savings(flagged, tariff, shift_fraction=shift_fraction)

    recs = generate_recommendations(
        demand_flagged, tariff,
        n_anomalies_forecast=int(flagged["is_anomaly"].sum()),
        n_anomalies_historical=n_anomalies_historical,
        demand_summary=demand_summary, demand_config=demand_config,
        industry_type=industry_type,
    )
    rec_records = [
        db.RecommendationRecord(category=r.category.value, severity=r.severity.value,
                                 message=r.message, automatable=r.automatable)
        for r in recs
    ]
    run_id = db.save_forecast_run(
        company_id=company_id, source=source, data_source=load_result.source.value,
        horizon_hours=horizon_hours,
        peak_hours_flagged=int(flagged["is_peak_flag"].sum()),
        anomalies_forecast=int(flagged["is_anomaly"].sum()),
        anomalies_historical=n_anomalies_historical,
        demand_breach_hours=demand_summary.breach_hours,
        demand_warning_hours=demand_summary.warning_hours,
        estimated_penalty=demand_summary.total_estimated_penalty,
        baseline_cost=savings.baseline_cost, optimized_cost=savings.optimized_cost,
        savings_pct=savings.savings_pct, monthly_savings_est=savings.monthly_savings,
        model_mae_kw=train_result.mae, recommendations=rec_records,
        scenario=scenario, profile=profile,
    )
    consultant_result = consultant.run_consultant(company_id)

    return {
        "forecast_run_id": run_id,
        "data_source": load_result.source.value,
        "data_quality": load_result.quality.to_dict() if load_result.quality is not None else None,
        "forecast": future.to_dict(orient="records"),
        "peak_hours_flagged": int(flagged["is_peak_flag"].sum()),
        "anomalies_forecast": int(flagged["is_anomaly"].sum()),
        "anomalies_historical": n_anomalies_historical,
        "model": {
            "mae_kw": train_result.mae, "rmse_kw": train_result.rmse,
            "arima_order": train_result.arima_order,
            "rf_weight": train_result.rf_weight, "arima_weight": train_result.arima_weight,
        },
        "demand_summary": {
            "breach_hours": demand_summary.breach_hours,
            "warning_hours": demand_summary.warning_hours,
            "peak_forecast_kw": demand_summary.peak_forecast_kw,
            "total_estimated_penalty": demand_summary.total_estimated_penalty,
        },
        "savings": {
            "baseline_cost": savings.baseline_cost,
            "optimized_cost": savings.optimized_cost,
            "savings_pct": savings.savings_pct,
            "estimated_monthly_savings": savings.monthly_savings,
        },
        "recommendations": [
            {"category": r.category.value, "severity": r.severity.value,
             "message": r.message, "automatable": r.automatable}
            for r in recs
        ],
        "consultant_notes": consultant_result,
    }


# --- Company signup / key management (signup itself needs no auth — it's how a key is issued) ---

@app.post("/signup")
def signup(payload: CompanySignupRequest, request: Request):
    """
    Creates a new company and returns its API key ONCE. Only the key's
    hash is stored — there is no way to retrieve it again. Losing it means
    calling /rotate-key (which itself requires the current key) or having
    an administrator inspect the database directly.
    """
    enforce_signup_rate_limit(request)
    try:
        record = db.CompanyRecord(
            name=payload.name, tier=payload.tier, sanctioned_load_kw=payload.sanctioned_load_kw,
            industry_type=payload.industry_type, shift_pattern=payload.shift_pattern,
            connection_type=payload.connection_type,
        )
        company_id, raw_key = db.create_company(record)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    log.info("New company signed up: #%s (%s)", company_id, payload.name)
    return {"company_id": company_id, "api_key": raw_key,
            "warning": "Save this key now — it cannot be shown again."}


@app.post("/rotate-key")
def rotate_key(company: CompanyContext = Depends(require_company)):
    new_key = db.rotate_api_key(company.company_id)
    db.log_audit_event(company.company_id, action="api_key_rotated")
    return {"api_key": new_key, "warning": "Save this key now — the previous key no longer works."}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/whatts-on")
def whatts_on(payload: WhattsOnRequest, company: CompanyContext = Depends(require_company)):
    """Answer an MSME energy question from the latest persisted WattWise run."""
    company_record = db.get_company(company.company_id)
    runs = db.get_recent_forecast_runs(company.company_id, limit=1)
    if not runs:
        return {
            "assistant": "WhattsOn",
            "answer": "Run a forecast first. Then ask me about demand, sanctioned-load risk, savings, anomalies, model accuracy, or recommendations.",
        }
    latest = runs[0]
    recs = db.get_recommendations_for_run(latest["id"], company.company_id)
    notes = db.get_consultant_notes(company.company_id, limit=5)
    training = db.get_recent_training_runs(company.company_id, limit=1)
    if training:
        latest_training = training[0]
        latest = {**latest,
                  "model_mae_kw": latest_training.get("mae_kw", latest.get("model_mae_kw")),
                  "model_rmse_kw": latest_training.get("rmse_kw"),
                  "rf_weight": latest_training.get("rf_weight"),
                  "arima_weight": latest_training.get("arima_weight")}
    context = context_from_api_summary(
        company_name=company_record.get("name", "your MSME") if company_record else "your MSME",
        industry=company_record.get("industry_type") if company_record else None,
        sanctioned_load_kw=company_record.get("sanctioned_load_kw") if company_record else None,
        run=latest, recommendations=recs, consultant_notes=notes,
    )
    response = whatts_on_answer(payload.question, context)
    db.log_audit_event(company.company_id, action="whatts_on_question")
    return {"assistant": "WhattsOn", "answer": response, "forecast_run_id": latest["id"]}


# --- Core pipeline ---

@app.post("/train")
def train(payload: TrainRequest, request: Request, company: CompanyContext = Depends(require_company)):
    enforce_train_rate_limit(request, company)
    _validate_scenario(payload.scenario)
    company_record = db.get_company(company.company_id)
    shift_pattern = _company_shift_pattern(company_record)

    try:
        load_result = load_consumption_data(
            force_demo=True, scenario=payload.scenario, shift_pattern=shift_pattern,
            sanctioned_load_kw=company_record.get("sanctioned_load_kw"), anchor_to_today=True,
        )
        train_result = train_ensemble(
            load_result.df, shift_pattern=shift_pattern, model_dir=_company_model_dir(company.company_id),
        )
    except (DataLoadError, InsufficientDataError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    run_id = db.save_training_run(
        company_id=company.company_id, data_source=load_result.source.value, mae_kw=train_result.mae,
        rmse_kw=train_result.rmse, arima_order=train_result.arima_order,
        rf_weight=train_result.rf_weight, arima_weight=train_result.arima_weight, scenario=payload.scenario,
    )
    db.log_audit_event(company.company_id, action="train_triggered", detail={"scenario": payload.scenario})

    return {
        "training_run_id": run_id, "data_source": load_result.source.value,
        "mae_kw": train_result.mae, "rmse_kw": train_result.rmse,
        "rf_weight": train_result.rf_weight, "arima_weight": train_result.arima_weight,
    }


@app.post("/forecast")
def forecast(payload: ForecastRequest, request: Request, company: CompanyContext = Depends(require_company)):
    enforce_forecast_rate_limit(request, company)
    _validate_scenario(payload.scenario)
    company_record = db.get_company(company.company_id)
    if company_record is None:
        raise HTTPException(status_code=404, detail="Company not found.")
    shift_pattern = _company_shift_pattern(company_record)

    try:
        load_result = load_consumption_data(
            force_demo=True, scenario=payload.scenario, shift_pattern=shift_pattern,
            sanctioned_load_kw=company_record.get("sanctioned_load_kw"), anchor_to_today=True,
        )
        result = _run_pipeline(
            company.company_id, load_result, shift_pattern, company_record.get("sanctioned_load_kw"),
            payload.horizon_hours, payload.shift_fraction, payload.ci_level,
            source="api", scenario=payload.scenario, profile=company_record.get("tier"),
            industry_type=company_record.get("industry_type"),
        )
    except (DataLoadError, InsufficientDataError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return result


@app.post("/forecast/upload")
async def forecast_from_upload(
    request: Request,
    file: UploadFile = File(...),
    horizon_hours: int = Query(default=24, ge=1, le=8760),
    shift_fraction: float = Query(default=0.3, ge=0.0, le=1.0),
    ci_level: float = Query(default=0.9, gt=0.0, lt=1.0),
    company: CompanyContext = Depends(require_company),
):
    """Forecasts against a real uploaded consumption file instead of demo data."""
    enforce_forecast_rate_limit(request, company)
    company_record = db.get_company(company.company_id)
    if company_record is None:
        raise HTTPException(status_code=404, detail="Company not found.")
    shift_pattern = _company_shift_pattern(company_record)

    contents = await file.read()
    try:
        load_result = load_from_upload(contents, file.filename)
        result = _run_pipeline(
            company.company_id, load_result, shift_pattern, company_record.get("sanctioned_load_kw"),
            horizon_hours, shift_fraction, ci_level,
            source="api", scenario=None, profile=company_record.get("tier"),
            industry_type=company_record.get("industry_type"),
        )
    except (DataLoadError, InsufficientDataError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return result


@app.get("/history")
def history(limit: int = Query(default=20, ge=1, le=500), company: CompanyContext = Depends(require_company)):
    return {"forecast_runs": db.get_recent_forecast_runs(company.company_id, limit=limit)}


@app.get("/consultant")
def get_consultant_notes(tier: Optional[str] = None, company: CompanyContext = Depends(require_company)):
    return {"notes": db.get_consultant_notes(company.company_id, tier=tier)}


@app.get("/audit-log")
def get_audit_log(limit: int = Query(default=100, ge=1, le=500), company: CompanyContext = Depends(require_company)):
    return {"entries": db.get_audit_log(company.company_id, limit=limit)}
