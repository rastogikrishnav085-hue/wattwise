"""
consultant.py
--------------
Trend-aware advisory layer, sitting above recommendations.py.

recommendations.py answers "what should this MSME do about THIS forecast
run." It has no memory — it fires the same message pattern every time,
regardless of what happened in previous runs. This module adds the two
tiers that need history to be meaningful:

  - Tier 1 (immediate)  : unchanged, still recommendations.py, still saved
                          to recommendations_log per forecast run.
  - Tier 2 (trending)   : "is this getting better or worse across recent
                          runs" — reads forecast_runs history via database.py.
  - Tier 3 (strategic)  : "is there a structural decision worth making" —
                          looks at a longer window and a bigger threshold.

Both new tiers write to consultant_notes so they show up in a history view,
not just the instant they're generated.

Numbers presented as benchmarks or estimates (e.g. DISCOM contract-revision
fees) are explicitly labeled as estimates in the generated message text —
do not strip that qualifier when displaying these notes; the actual fee
varies by DISCOM and must be confirmed before anyone acts on it.
"""

from __future__ import annotations

import numpy as np

from . import database as db
from .logging_setup import get_logger

log = get_logger(__name__)

MIN_RUNS_FOR_TREND = 3
MIN_RUNS_FOR_STRATEGIC = 5
BREACH_FREQUENCY_ALERT_THRESHOLD = 0.4  # 40%+ of recent runs breaching triggers a strategic note
FLAT_TOLERANCE_PCT = 5.0


def _trend_direction(values: list[float]) -> str:
    """Compares the first vs. last value in a chronological series. Simple by
    design — this needs to be explainable to a factory owner, not just accurate."""
    if len(values) < 2:
        return "flat"
    first, last = values[0], values[-1]
    if first == 0:
        return "flat" if last == 0 else "rising"
    pct_change = (last - first) / abs(first) * 100
    if pct_change > FLAT_TOLERANCE_PCT:
        return "rising"
    if pct_change < -FLAT_TOLERANCE_PCT:
        return "falling"
    return "flat"


def generate_trending_notes(company_id: int, db_path: str = db.DB_PATH) -> list[dict]:
    """
    Tier 2. Compares the current run's context against the company's own
    recent history (already persisted by every prior save_forecast_run call)
    rather than evaluating a single snapshot in isolation.
    """
    runs = db.get_recent_forecast_runs(company_id, limit=10, db_path=db_path)
    notes: list[dict] = []
    if len(runs) < MIN_RUNS_FOR_TREND:
        return notes

    chronological = list(reversed(runs))  # get_recent_forecast_runs is newest-first

    penalty_series = [r["estimated_penalty"] for r in chronological]
    anomaly_series = [r["anomalies_forecast"] + r["anomalies_historical"] for r in chronological]

    penalty_trend = _trend_direction(penalty_series)
    if penalty_trend == "rising":
        msg = (
            f"Estimated penalty exposure has risen across the last {len(chronological)} forecast runs "
            f"(from Rs.{penalty_series[0]:,.0f} to Rs.{penalty_series[-1]:,.0f}). Before this becomes a "
            "recurring cost, check whether recent load growth is temporary (a large order, a seasonal "
            "peak) or a new baseline that needs a longer-term response."
        )
        note_id = db.save_consultant_note(
            company_id, tier="trending", category="demand_limit",
            message=msg, trend_direction="rising", db_path=db_path,
        )
        notes.append({"id": note_id, "tier": "trending", "message": msg, "trend_direction": "rising"})

    anomaly_trend = _trend_direction(anomaly_series)
    if anomaly_trend == "falling":
        msg = (
            f"Anomaly counts have fallen across the last {len(chronological)} forecast runs "
            f"(from {anomaly_series[0]} to {anomaly_series[-1]}). If a maintenance fix or process "
            "change was made recently, this is evidence it's working."
        )
        note_id = db.save_consultant_note(
            company_id, tier="trending", category="anomaly",
            message=msg, trend_direction="falling", db_path=db_path,
        )
        notes.append({"id": note_id, "tier": "trending", "message": msg, "trend_direction": "falling"})
    elif anomaly_trend == "rising":
        msg = (
            f"Anomaly counts have risen across the last {len(chronological)} forecast runs "
            f"(from {anomaly_series[0]} to {anomaly_series[-1]}). Worth a physical check on equipment "
            "active during the flagged hours before a spike becomes a breakdown."
        )
        note_id = db.save_consultant_note(
            company_id, tier="trending", category="anomaly",
            message=msg, trend_direction="rising", db_path=db_path,
        )
        notes.append({"id": note_id, "tier": "trending", "message": msg, "trend_direction": "rising"})

    return notes


def generate_strategic_notes(company_id: int, db_path: str = db.DB_PATH) -> list[dict]:
    """
    Tier 3. Looks at breach frequency over a longer window; when it's high
    enough to matter financially, suggests a structural change (e.g.
    revisiting the sanctioned load contract) instead of another daily tactic.
    """
    runs = db.get_recent_forecast_runs(company_id, limit=30, db_path=db_path)
    notes: list[dict] = []
    if len(runs) < MIN_RUNS_FOR_STRATEGIC:
        return notes

    breach_runs = sum(1 for r in runs if r["demand_breach_hours"] > 0)
    breach_frequency = breach_runs / len(runs)

    if breach_frequency >= BREACH_FREQUENCY_ALERT_THRESHOLD:
        company = db.get_company(company_id, db_path=db_path)
        sanctioned = company.get("sanctioned_load_kw") if company else None
        limit_note = f" (current contract limit: {sanctioned:.0f} kW)" if sanctioned else ""
        msg = (
            f"{breach_runs} of the last {len(runs)} forecasts ({breach_frequency:.0%}) showed a "
            f"sanctioned-load breach{limit_note}. At this frequency, the recurring penalty cost is "
            "likely higher than the one-time fee to formally raise your contract demand with the "
            "DISCOM — worth requesting a quote for a contract-demand revision to compare against a "
            "year of penalty exposure at the current rate. (This is an estimate based on breach "
            "frequency alone — confirm the actual revision fee and penalty rate with your DISCOM "
            "before acting on it.)"
        )
        note_id = db.save_consultant_note(
            company_id, tier="strategic", category="demand_limit",
            message=msg, trend_direction=None, db_path=db_path,
        )
        notes.append({"id": note_id, "tier": "strategic", "message": msg})

    return notes


def run_consultant(company_id: int, db_path: str = db.DB_PATH) -> dict:
    """
    Entry point — call this after save_forecast_run() in the normal
    pipeline (dashboard and API both). Tier 1 (immediate) is unchanged and
    still comes from recommendations.generate_recommendations(), saved to
    recommendations_log as before; this function only adds tiers 2 and 3.
    """
    return {
        "trending": generate_trending_notes(company_id, db_path=db_path),
        "strategic": generate_strategic_notes(company_id, db_path=db_path),
    }
