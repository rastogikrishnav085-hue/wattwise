"""
pdf_report.py
--------------
Renders the same content as report.py as an actual PDF using fpdf2 (pure
Python, no native/system dependencies).

Same two optional additions as report.py: forecast_ci and consultant_notes.
Both default to None so existing callers are unaffected.

Font note unchanged: FPDF's built-in "Helvetica" core font is Latin-1
only, so "Rs." is used instead of "₹" here specifically — the Streamlit
UI, CSV export, and Markdown report all keep the real ₹ symbol since they
don't share this font constraint.
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional

from fpdf import FPDF

from .flags import TariffWindow
from .demand_limit import DemandLimitConfig, DemandSummary
from .recommendations import Recommendation

_DARK = (20, 28, 45)
_MUTED = (110, 120, 140)
_ACCENT = (245, 166, 35)

_ASCII_SAFE_MAP = {
    "\u2014": "--", "\u2013": "-", "\u20b9": "Rs.",
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2026": "...", "\u2192": "->",
}


def _sanitize(text: str) -> str:
    for src, dst in _ASCII_SAFE_MAP.items():
        text = text.replace(src, dst)
    return text.encode("latin-1", errors="replace").decode("latin-1")


class _ReportPDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 18)
        self.set_text_color(*_DARK)
        self.cell(0, 10, "WattWise -- Forecast Summary Report", new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*_MUTED)
        self.cell(0, 6, "SIH 2026 -- Smart Energy Forecasting & Peak-Load Optimization", new_x="LMARGIN", new_y="NEXT")
        self.ln(3)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(*_MUTED)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")


def _section(pdf: _ReportPDF, title: str) -> None:
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(*_DARK)
    pdf.cell(0, 8, _sanitize(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*_ACCENT)
    pdf.set_line_width(0.5)
    y = pdf.get_y()
    pdf.line(10, y, 55, y)
    pdf.ln(2)


def _bullet(pdf: _ReportPDF, text: str) -> None:
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(35, 35, 35)
    pdf.multi_cell(0, 6, f"-  {_sanitize(text)}", new_x="LMARGIN", new_y="NEXT")


def build_pdf_report(
    data_source: str,
    scenario: str | None,
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
    predicted_peak_kw: float,
    predicted_peak_time: str,
    predicted_avg_kw: float,
    predicted_total_kwh: float,
    forecast_ci: Optional[tuple[float, float, int]] = None,
    consultant_notes: Optional[dict] = None,
) -> bytes:
    """Returns raw PDF bytes, ready for a Streamlit download_button or a FastAPI StreamingResponse."""
    pdf = _ReportPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    src_note = f" (scenario: {scenario})" if data_source == "demo_synthetic_dataset" and scenario else ""
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_MUTED)
    pdf.cell(0, 6, _sanitize(f"Generated {generated_at} -- data source: {data_source}{src_note}"), new_x="LMARGIN", new_y="NEXT")

    _section(pdf, "Predicted Results")
    _bullet(pdf, f"Predicted peak demand: {predicted_peak_kw:.2f} kW at {predicted_peak_time}")
    if forecast_ci is not None:
        lower, upper, level_pct = forecast_ci
        _bullet(pdf, f"Peak forecast confidence interval ({level_pct}%): {lower:.2f}-{upper:.2f} kW")
    _bullet(pdf, f"Predicted average demand: {predicted_avg_kw:.2f} kW")
    _bullet(pdf, f"Predicted total consumption over horizon: {predicted_total_kwh:.1f} kWh")

    _section(pdf, "Model")
    _bullet(pdf, f"Ensemble: ARIMA{tuple(arima_order)} + Random Forest "
                 f"(RF weight {rf_weight:.0%} / ARIMA weight {1 - rf_weight:.0%})")
    _bullet(pdf, f"Test-set accuracy: MAE {model_mae:.3f} kW, RMSE {model_rmse:.3f} kW")

    _section(pdf, "Peak-Tariff & Anomalies")
    _bullet(pdf, f"Peak-tariff hours flagged: {n_peak_hours} (Rs.{tariff.peak_rate:.0f}/kWh window)")
    _bullet(pdf, f"Anomalies -- forecast window: {n_anomalies_forecast} | last 30 days history: {n_anomalies_historical}")

    _section(pdf, "Sanctioned-Load / Contract-Demand Risk")
    _bullet(pdf, f"Contract limit: {demand_config.sanctioned_load_kw:.0f} kW "
                 f"(penalty Rs.{demand_config.penalty_rate_per_kw:.0f}/kW excess)")
    _bullet(pdf, f"Breach hours: {demand_summary.breach_hours} | Warning hours: {demand_summary.warning_hours}")
    _bullet(pdf, f"Peak forecasted demand: {demand_summary.peak_forecast_kw:.1f} kW")
    _bullet(pdf, f"Estimated penalty exposure: Rs.{demand_summary.total_estimated_penalty:,.0f}")

    _section(pdf, "Savings (Load-Shift Optimization)")
    _bullet(pdf, f"Baseline cost: Rs.{savings_baseline:,.0f}")
    _bullet(pdf, f"Optimized cost: Rs.{savings_optimized:,.0f} ({savings_pct:.1f}% reduction)")
    _bullet(pdf, f"Projected monthly savings: Rs.{monthly_savings_est:,.0f}")

    _section(pdf, "Recommendations")
    if not recommendations:
        _bullet(pdf, "No recommendations generated for the current configuration.")
    else:
        for rec in recommendations:
            tag = " (automatable)" if rec.automatable else ""
            _bullet(pdf, f"[{rec.severity.value.upper()}] {rec.message}{tag}")

    if consultant_notes:
        trending = consultant_notes.get("trending") or []
        strategic = consultant_notes.get("strategic") or []
        if trending or strategic:
            _section(pdf, "Consultant Notes")
            for note in trending:
                _bullet(pdf, f"[TRENDING] {note['message']}")
            for note in strategic:
                _bullet(pdf, f"[STRATEGIC] {note['message']}")

    pdf.ln(6)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(*_MUTED)
    pdf.multi_cell(
        0, 5,
        "WattWise -- SIH 2026. Advisory, human-in-the-loop recommendations only; "
        "no automated control action is taken by this system.",
        new_x="LMARGIN", new_y="NEXT",
    )

    return bytes(pdf.output())
