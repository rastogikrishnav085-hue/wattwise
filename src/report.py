"""
report.py
----------
Builds a one-page, judge/owner-readable Markdown summary from the current
forecast/flag/savings/demand/recommendation state.

Two additions, both optional (default None) so existing callers don't
need to change anything to keep working:
  - forecast_ci: (lower, upper, level_pct) — shows the confidence interval
    around the peak forecast instead of a bare point number next to the
    sanctioned-load limit.
  - consultant_notes: {"trending": [...], "strategic": [...]} from
    consultant.run_consultant() — surfaces the trend-aware advisory tiers
    in the same leave-behind document, not just in the live dashboard.
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from .flags import TariffWindow
from .demand_limit import DemandLimitConfig, DemandSummary
from .recommendations import Recommendation


def build_summary_report(
    data_source: str,
    scenario: str,
    tariff: TariffWindow,
    demand_config: DemandLimitConfig,
    demand_summary: DemandSummary,
    savings_baseline: float,
    savings_optimized: float,
    savings_pct: float,
    monthly_savings_est: float,
    n_peak_hours: int,
    n_anomalies_forecast: int,
    n_anomalies_historical: int,
    model_mae: float,
    model_rmse: float,
    arima_order: tuple,
    rf_weight: float,
    recommendations: list[Recommendation],
    forecast_ci: Optional[tuple[float, float, int]] = None,
    consultant_notes: Optional[dict] = None,
) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# WattWise — Forecast Summary Report",
        "",
        f"*Generated {generated_at} · data source: `{data_source}`"
        + (f" (scenario: `{scenario}`)" if data_source == "demo_synthetic_dataset" else "") + "*",
        "",
        "## Model",
        f"- Ensemble: ARIMA{tuple(arima_order)} + Random Forest "
        f"(RF weight {rf_weight:.0%} / ARIMA weight {1 - rf_weight:.0%})",
        f"- Test-set accuracy: MAE {model_mae:.3f} kW, RMSE {model_rmse:.3f} kW",
        "",
        "## Next-24h Forecast Summary",
        f"- Peak-tariff hours flagged: {n_peak_hours} / 24 (₹{tariff.peak_rate:.0f}/kWh window)",
        f"- Anomalies — forecast window: {n_anomalies_forecast} · last 30 days history: {n_anomalies_historical}",
    ]

    if forecast_ci is not None:
        lower, upper, level_pct = forecast_ci
        lines.append(f"- Peak forecast confidence interval ({level_pct}%): {lower:.1f}–{upper:.1f} kW")

    lines += [
        "",
        "## Sanctioned-Load / Contract-Demand Risk",
        f"- Contract limit: {demand_config.sanctioned_load_kw:.0f} kW "
        f"(penalty rate ₹{demand_config.penalty_rate_per_kw:.0f}/kW excess)",
        f"- Breach hours: {demand_summary.breach_hours} · Warning hours: {demand_summary.warning_hours}",
        f"- Peak forecasted demand: {demand_summary.peak_forecast_kw:.1f} kW",
        f"- Estimated penalty exposure: ₹{demand_summary.total_estimated_penalty:,.0f}",
        "",
        "## Savings (Load-Shift Optimization)",
        f"- Baseline cost (24h): ₹{savings_baseline:,.0f}",
        f"- Optimized cost (24h): ₹{savings_optimized:,.0f} ({savings_pct:.1f}% reduction)",
        f"- Projected monthly savings: ₹{monthly_savings_est:,.0f}",
        "",
        "## Recommendations",
    ]

    if not recommendations:
        lines.append("- No recommendations generated for the current configuration.")
    else:
        for rec in recommendations:
            tag = " *(automatable)*" if rec.automatable else ""
            lines.append(f"- **[{rec.severity.value.upper()}]** {rec.message}{tag}")

    if consultant_notes:
        trending = consultant_notes.get("trending") or []
        strategic = consultant_notes.get("strategic") or []
        if trending or strategic:
            lines += ["", "## Consultant Notes"]
            if trending:
                lines.append("### Trending (this week vs. last)")
                for note in trending:
                    lines.append(f"- {note['message']}")
            if strategic:
                lines.append("### Strategic (structural)")
                for note in strategic:
                    lines.append(f"- {note['message']}")

    lines += [
        "",
        "---",
        "*WattWise — SIH 2026. Advisory, human-in-the-loop recommendations only; "
        "no automated control action is taken by this system.*",
    ]

    return "\n".join(lines)
