"""
WhattsOn — WattWise conversational energy assistant.

WhattsOn is a lightweight, deterministic assistant that translates the
structured outputs of the WattWise analytics engine into plain-language
answers for MSME operators.

The module supports two modes:
1. Deterministic WattWise answers.
2. Optional Gemini enhancement.

If Gemini is unavailable, rate-limited, or returns an error, WhattsOn
automatically falls back to the deterministic WattWise answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import json
import os
import re
import time


@dataclass
class WhattsOnContext:
    company_name: str = "your MSME"
    industry: str | None = None
    sanctioned_load_kw: float | None = None
    forecast_peak_kw: float | None = None
    forecast_avg_kw: float | None = None
    breach_hours: int = 0
    warning_hours: int = 0
    estimated_penalty: float = 0.0
    baseline_cost: float = 0.0
    optimized_cost: float = 0.0
    savings_pct: float = 0.0
    monthly_savings: float = 0.0
    forecast_anomalies: int = 0
    historical_anomalies: int = 0
    mae_kw: float | None = None
    rmse_kw: float | None = None
    rf_weight: float | None = None
    arima_weight: float | None = None
    ci_level: float | None = None
    data_source: str | None = None
    horizon_hours: int | None = None
    recommendations: list[str] = field(default_factory=list)
    consultant_notes: list[str] = field(default_factory=list)


def _money(value: float) -> str:
    return f"₹{value:,.0f}"


def _pct(value: float) -> str:
    return f"{value:.1f}%"


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _risk_line(ctx: WhattsOnContext) -> str:
    if ctx.breach_hours > 0:
        return (
            f"There are {ctx.breach_hours} forecast hour(s) above the "
            f"sanctioned load, with estimated penalty exposure of "
            f"{_money(ctx.estimated_penalty)}."
        )

    if ctx.warning_hours > 0:
        return (
            f"There are {ctx.warning_hours} forecast hour(s) close to "
            f"the sanctioned-load limit."
        )

    if ctx.sanctioned_load_kw and ctx.forecast_peak_kw is not None:
        return (
            f"The forecast peak is {ctx.forecast_peak_kw:.1f} kW "
            f"against a {ctx.sanctioned_load_kw:.1f} kW limit."
        )

    return "No sanctioned-load risk summary is available yet."


def deterministic_answer(
    question: str,
    context: WhattsOnContext,
) -> str:
    """
    Answer common MSME energy questions using only structured
    WattWise context.
    """

    ctx = context
    q = _normalise(question)

    if not q:
        return (
            "Ask me about your forecast, peak demand, sanctioned load, "
            "savings, anomalies, model accuracy, or recommendations."
        )

    # ---------------------------------------------------------
    # FORECAST
    # ---------------------------------------------------------
    if any(
        keyword in q
        for keyword in (
            "forecast",
            "tomorrow",
            "predicted",
            "prediction",
        )
    ):
        if (
            ctx.forecast_peak_kw is None
            or ctx.forecast_avg_kw is None
        ):
            return (
                "A forecast is not available yet. "
                "Run a forecast first."
            )

        horizon = ""

        if ctx.horizon_hours:
            horizon = (
                f" for the next {ctx.horizon_hours} hours"
            )

        response = (
            f"WattWise's latest forecast{horizon} shows an "
            f"average demand of {ctx.forecast_avg_kw:.1f} kW "
            f"and a peak demand of {ctx.forecast_peak_kw:.1f} kW."
        )

        if ctx.sanctioned_load_kw:
            response += (
                f" The sanctioned-load limit is "
                f"{ctx.sanctioned_load_kw:.1f} kW."
            )

        if ctx.breach_hours > 0:
            response += (
                f" {ctx.breach_hours} forecast hour(s) are "
                f"above the sanctioned-load limit."
            )
        elif ctx.warning_hours > 0:
            response += (
                f" {ctx.warning_hours} forecast hour(s) are "
                f"close to the sanctioned-load limit."
            )

        return response

    # ---------------------------------------------------------
    # COST / TARIFF
    # ---------------------------------------------------------
    if (
        any(
            keyword in q
            for keyword in (
                "why",
                "cost",
                "bill",
                "expensive",
                "tariff",
            )
        )
        and any(
            keyword in q
            for keyword in (
                "tomorrow",
                "forecast",
                "electricity",
                "power",
                "bill",
                "cost",
            )
        )
    ):
        return (
            f"Your forecast average demand is "
            f"{ctx.forecast_avg_kw:.1f} kW and the forecast peak is "
            f"{ctx.forecast_peak_kw:.1f} kW. WattWise classifies "
            f"future hours into peak, shoulder and off-peak tariff "
            f"windows. The current load-shifting scenario estimates "
            f"{_pct(ctx.savings_pct)} potential savings. "
            f"{_risk_line(ctx)}"
        )

    # ---------------------------------------------------------
    # SANCTIONED LOAD / RISK
    # ---------------------------------------------------------
    if any(
        keyword in q
        for keyword in (
            "sanction",
            "limit",
            "breach",
            "contract demand",
            "penalty",
            "risk",
        )
    ):
        return (
            _risk_line(ctx)
            + " Review the flagged hours before scheduling "
              "flexible high-load operations."
        )

    # ---------------------------------------------------------
    # SAVINGS
    # ---------------------------------------------------------
    if any(
        keyword in q
        for keyword in (
            "save",
            "savings",
            "shift",
            "production",
        )
    ):
        return (
            "The current scenario moves a configurable share of "
            "peak load to off-peak periods. "
            f"Estimated savings are {_money(ctx.monthly_savings)} "
            f"per month ({_pct(ctx.savings_pct)} of the "
            f"forecast-period baseline). "
            f"Baseline cost is {_money(ctx.baseline_cost)} versus "
            f"{_money(ctx.optimized_cost)} after the simulated shift. "
            "Treat tariff and shift assumptions as estimates."
        )

    # ---------------------------------------------------------
    # ANOMALIES
    # ---------------------------------------------------------
    if any(
        keyword in q
        for keyword in (
            "anomal",
            "abnormal",
            "spike",
            "unusual",
        )
    ):
        return (
            f"WattWise detected {ctx.forecast_anomalies} "
            f"forecast anomaly/anomalies and "
            f"{ctx.historical_anomalies} historical "
            "anomaly/anomalies. Shift-boundary behaviour is "
            "accounted for to reduce predictable industrial "
            "false alarms. Investigate unexpected spikes "
            "outside normal operating windows."
        )

    # ---------------------------------------------------------
    # MODEL ACCURACY
    # ---------------------------------------------------------
    if any(
        keyword in q
        for keyword in (
            "accuracy",
            "accurate",
            "mae",
            "rmse",
            "model",
        )
    ):
        if (
            ctx.mae_kw is None
            or ctx.rmse_kw is None
        ):
            return (
                "Model accuracy metrics are not available until "
                "a forecast has been trained."
            )

        rf = (
            f"{ctx.rf_weight:.0%}"
            if ctx.rf_weight is not None
            else "unknown"
        )

        arima = (
            f"{ctx.arima_weight:.0%}"
            if ctx.arima_weight is not None
            else "unknown"
        )

        return (
            f"On the held-out test period, WattWise reports "
            f"MAE {ctx.mae_kw:.2f} kW and RMSE "
            f"{ctx.rmse_kw:.2f} kW. The ensemble uses "
            f"{rf} Random Forest and {arima} ARIMA. "
            "Accuracy is dataset-dependent, so these metrics "
            "should be used for this MSME's data rather than "
            "as a universal accuracy percentage."
        )

    # ---------------------------------------------------------
    # RECOMMENDATIONS
    # ---------------------------------------------------------
    if any(
        keyword in q
        for keyword in (
            "what should",
            "recommend",
            "recommendation",
            "do tomorrow",
            "next step",
        )
    ):
        if ctx.recommendations:
            return (
                "Based on the latest run, the key actions are: "
                + " ".join(
                    f"{i + 1}. {item}"
                    for i, item in enumerate(
                        ctx.recommendations[:4]
                    )
                )
            )

        return (
            "No recommendation list is available yet. "
            "Run a forecast first."
        )

    # ---------------------------------------------------------
    # TRENDS / CONSULTANT
    # ---------------------------------------------------------
    if any(
        keyword in q
        for keyword in (
            "trend",
            "getting worse",
            "getting better",
            "week",
            "strategic",
        )
    ):
        if ctx.consultant_notes:
            return (
                "Consultant insights: "
                + " ".join(ctx.consultant_notes[:3])
            )

        return (
            "There is not enough forecast-run history yet for "
            "a meaningful trend or strategic insight."
        )

    # ---------------------------------------------------------
    # DATA SOURCE
    # ---------------------------------------------------------
    if any(
        keyword in q
        for keyword in (
            "data",
            "upload",
            "dataset",
            "real",
        )
    ):
        source = (
            ctx.data_source or "current run"
        ).replace("_", " ")

        return (
            f"The current forecast uses {source}. WattWise can "
            "also process a user's own CSV/TXT electricity "
            "dataset through validation, hourly resampling, "
            "feature engineering and the same forecasting pipeline."
        )

    # ---------------------------------------------------------
    # SAFE FALLBACK
    # ---------------------------------------------------------
    return (
        "I can explain your latest WattWise forecast, "
        "sanctioned-load risk, estimated savings, anomalies, "
        "model accuracy, recommendations, or consultant trends. "
        "Try asking a specific question."
    )


def _context_payload(
    ctx: WhattsOnContext,
) -> dict[str, Any]:
    """Return only structured WattWise facts that Gemini may use."""

    return {
        "company_name": ctx.company_name,
        "industry": ctx.industry,
        "sanctioned_load_kw": ctx.sanctioned_load_kw,
        "forecast_peak_kw": ctx.forecast_peak_kw,
        "forecast_avg_kw": ctx.forecast_avg_kw,
        "breach_hours": ctx.breach_hours,
        "warning_hours": ctx.warning_hours,
        "estimated_penalty_inr": ctx.estimated_penalty,
        "baseline_cost_inr": ctx.baseline_cost,
        "optimized_cost_inr": ctx.optimized_cost,
        "savings_pct": ctx.savings_pct,
        "monthly_savings_inr": ctx.monthly_savings,
        "forecast_anomalies": ctx.forecast_anomalies,
        "historical_anomalies": ctx.historical_anomalies,
        "mae_kw": ctx.mae_kw,
        "rmse_kw": ctx.rmse_kw,
        "rf_weight": ctx.rf_weight,
        "arima_weight": ctx.arima_weight,
        "confidence_level": ctx.ci_level,
        "data_source": ctx.data_source,
        "horizon_hours": ctx.horizon_hours,
        "recommendations": ctx.recommendations[:6],
        "consultant_notes": ctx.consultant_notes[:6],
    }


def _gemini_answer(
    question: str,
    context: WhattsOnContext,
) -> str | None:
    """
    Use Gemini when available.

    429/503/transient failures are retried once.
    If Gemini still fails, return None so the deterministic
    WattWise answer is used.
    """

    api_key = os.getenv(
        "GEMINI_API_KEY",
        "",
    ).strip()

    use_gemini = os.getenv(
        "WATTWISE_USE_GEMINI",
        "false",
    ).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    if not api_key or not use_gemini:
        return None

    try:
        from google import genai

        client = genai.Client(
            api_key=api_key
        )

        model = (
            os.getenv(
                "GEMINI_MODEL",
                "gemini-3.8-flash",
            ).strip()
            or "gemini-3.8-flash"
        )

        payload = json.dumps(
            _context_payload(context),
            ensure_ascii=False,
        )

        prompt = (
            "You are WhattsOn, the WattWise energy assistant "
            "for MSMEs. "
            "Answer the user's question using ONLY the WattWise "
            "facts in the JSON context below. "
            "Do not invent measurements, tariffs, penalties, "
            "dates, savings, or recommendations. "
            "If a value is missing, say it is unavailable. "
            "Keep the answer concise and operational. "
            "Tariffs, shiftability assumptions, and penalty "
            "exposure are estimates unless explicitly stated "
            "otherwise. "
            "Never claim universal model accuracy; describe "
            "the supplied MAE/RMSE as held-out test metrics.\n\n"
            f"WattWise context:\n{payload}\n\n"
            f"User question: {question}"
        )

        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                )

                response_text = getattr(
                    response,
                    "text",
                    None,
                )

                if (
                    response_text
                    and response_text.strip()
                ):
                    return response_text.strip()

                return None

            except Exception as exc:
                error_text = str(exc).lower()

                transient = (
                    "429" in error_text
                    or "503" in error_text
                    or "service unavailable" in error_text
                    or "temporarily unavailable" in error_text
                    or "resource exhausted" in error_text
                )

                if not transient or attempt == 1:
                    return None

                time.sleep(2)

    except Exception:
        return None


def answer(
    question: str,
    context: WhattsOnContext,
) -> str:
    """
    Answer with optional Gemini enhancement and deterministic fallback.
    """

    gemini = _gemini_answer(
        question,
        context,
    )

    return (
        gemini
        if gemini
        else deterministic_answer(
            question,
            context,
        )
    )


def context_from_run(
    *,
    company_name: str,
    industry: str | None,
    sanctioned_load_kw: float | None,
    run: dict[str, Any],
) -> WhattsOnContext:
    """Build assistant context from the dashboard's last-run dictionary."""

    summary = run["demand_summary"]
    savings = run["savings"]
    train = run["train_result"]
    future = run["future"]

    recs = run.get(
        "recs",
        [],
    )

    consultant_result = (
        run.get("consultant_result")
        or {}
    )

    notes = []

    for tier in (
        "trending",
        "strategic",
    ):
        for item in consultant_result.get(
            tier,
            [],
        ):
            if item.get("message"):
                notes.append(
                    item["message"]
                )

    return WhattsOnContext(
        company_name=company_name,
        industry=industry,
        sanctioned_load_kw=sanctioned_load_kw,
        forecast_peak_kw=float(
            summary.peak_forecast_kw
        ),
        forecast_avg_kw=float(
            future["forecast_kw"].mean()
        ),
        breach_hours=int(
            summary.breach_hours
        ),
        warning_hours=int(
            summary.warning_hours
        ),
        estimated_penalty=float(
            summary.total_estimated_penalty
        ),
        baseline_cost=float(
            savings.baseline_cost
        ),
        optimized_cost=float(
            savings.optimized_cost
        ),
        savings_pct=float(
            savings.savings_pct
        ),
        monthly_savings=float(
            savings.monthly_savings
        ),
        forecast_anomalies=int(
            flagged_count(run)
        ),
        historical_anomalies=int(
            run.get(
                "n_anomalies_historical",
                0,
            )
        ),
        mae_kw=float(
            train.mae
        ),
        rmse_kw=float(
            train.rmse
        ),
        rf_weight=float(
            train.rf_weight
        ),
        arima_weight=float(
            train.arima_weight
        ),
        ci_level=float(
            run.get(
                "ci_level",
                0.9,
            )
        ),
        data_source=(
            run.get("load_result").source.value
            if run.get("load_result")
            else None
        ),
        horizon_hours=int(
            run.get(
                "horizon_hours",
                len(future),
            )
        ),
        recommendations=[
            r.message
            for r in recs
        ],
        consultant_notes=notes,
    )


def flagged_count(
    run: dict[str, Any],
) -> int:
    flagged = run.get(
        "flagged"
    )

    if flagged is None:
        return 0

    try:
        return int(
            flagged[
                "is_anomaly"
            ].sum()
        )

    except (
        KeyError,
        TypeError,
        AttributeError,
    ):
        return 0


def context_from_api_summary(
    *,
    company_name: str,
    industry: str | None,
    sanctioned_load_kw: float | None,
    run: dict[str, Any],
    recommendations: list[dict] | None = None,
    consultant_notes: list[dict] | None = None,
) -> WhattsOnContext:
    """
    Build context from the persisted forecast summary
    returned by the API/database.
    """

    model_mae = run.get(
        "model_mae_kw"
    )

    model_rmse = run.get(
        "model_rmse_kw"
    )

    rf_weight = run.get(
        "rf_weight"
    )

    arima_weight = run.get(
        "arima_weight"
    )

    recs = (
        recommendations
        or []
    )

    notes = (
        consultant_notes
        or []
    )

    return WhattsOnContext(
        company_name=company_name,
        industry=industry,
        sanctioned_load_kw=sanctioned_load_kw,
        forecast_peak_kw=None,
        forecast_avg_kw=None,
        breach_hours=int(
            run.get(
                "demand_breach_hours",
                0,
            )
            or 0
        ),
        warning_hours=int(
            run.get(
                "demand_warning_hours",
                0,
            )
            or 0
        ),
        estimated_penalty=float(
            run.get(
                "estimated_penalty",
                0,
            )
            or 0
        ),
        baseline_cost=float(
            run.get(
                "baseline_cost",
                0,
            )
            or 0
        ),
        optimized_cost=float(
            run.get(
                "optimized_cost",
                0,
            )
            or 0
        ),
        savings_pct=float(
            run.get(
                "savings_pct",
                0,
            )
            or 0
        ),
        monthly_savings=float(
            run.get(
                "monthly_savings_est",
                0,
            )
            or 0
        ),
        forecast_anomalies=int(
            run.get(
                "anomalies_forecast",
                0,
            )
            or 0
        ),
        historical_anomalies=int(
            run.get(
                "anomalies_historical",
                0,
            )
            or 0
        ),
        mae_kw=(
            float(model_mae)
            if model_mae is not None
            else None
        ),
        rmse_kw=(
            float(model_rmse)
            if model_rmse is not None
            else None
        ),
        rf_weight=(
            float(rf_weight)
            if rf_weight is not None
            else None
        ),
        arima_weight=(
            float(arima_weight)
            if arima_weight is not None
            else None
        ),
        data_source=run.get(
            "data_source"
        ),
        horizon_hours=int(
            run.get(
                "horizon_hours",
                0,
            )
            or 0
        ),
        recommendations=[
            r.get(
                "message",
                "",
            )
            for r in recs
            if r.get("message")
        ],
        consultant_notes=[
            n.get(
                "message",
                "",
            )
            for n in notes
            if n.get("message")
        ],
    )