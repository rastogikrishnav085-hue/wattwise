"""
app.py
-------
WattWise Streamlit dashboard.

Talks directly to the src package (same process, same database as api.py — see
database.py's module docstring) rather than going over HTTP.

Multi-tenancy works the same way as in the API: the person logs in with their company's
API key, which resolves to a company_id via database.get_company_by_api_key — the exact
same lookup security.require_company uses for API requests. The key lives only in
st.session_state for this browser session; nothing is written to disk.
"""

from __future__ import annotations
import json
import os
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import database as db
from src import consultant
from src.config import MODEL_DIR
from src.data_loader import load_consumption_data, load_from_upload, DataLoadError
from src.forecast import train_ensemble, forecast_next_n_hours, InsufficientDataError
from src.flags import TariffWindow, flag_peak_hours, detect_anomalies, detect_rolling_anomalies
from src.demand_limit import DemandLimitConfig, flag_demand_breaches, summarize_demand_risk
from src.savings import calculate_savings
from src.recommendations import generate_recommendations
from src.report import build_summary_report
from src.pdf_report import build_pdf_report
from src.logging_setup import get_logger
from src.whatts_on import answer as whatts_on_answer, context_from_run

log = get_logger(__name__)

st.set_page_config(page_title="WattWise", page_icon="⚡", layout="wide", initial_sidebar_state="expanded")

# ---------------------------------------------------------------------------
# Visual system
# ---------------------------------------------------------------------------

_THEME = {
    "dark": {
        "bg": "#0B1220",
        "surface": "#121B2B",
        "surface2": "#172337",
        "ink": "#EAF2F7",
        "muted": "#A9B8C7",
        "border": "#2A3A50",
        "teal": "#35C5A0",
        "teal_dark": "#0D7563",
        "green": "#35C995",
        "orange": "#F4B34A",
        "red": "#FF7272",
        "blue": "#8EA8C7",
        "plot": "plotly_dark",
        "grid": "rgba(234,242,247,0.09)",
        "sidebar_bg": "#071D1B",
        "sidebar_ink": "#F3FFFB",
    },
}

THEME = _THEME["dark"]

st.markdown(
    f"""
    <style>
    :root {{
        --ww-bg: {THEME['bg']};
        --ww-surface: {THEME['surface']};
        --ww-surface2: {THEME['surface2']};
        --ww-ink: {THEME['ink']};
        --ww-muted: {THEME['muted']};
        --ww-border: {THEME['border']};
        --ww-teal: {THEME['teal']};
        --ww-green: {THEME['green']};
        --ww-orange: {THEME['orange']};
        --ww-red: {THEME['red']};
        --ww-blue: {THEME['blue']};
    }}
    .stApp {{ background: var(--ww-bg); color: var(--ww-ink); }}
    .block-container {{ padding-top: 1.25rem; padding-bottom: 2rem; max-width: 1500px; }}
    [data-testid="stHeader"] {{ background: transparent; }}
    [data-testid="stMetricValue"] {{ font-size: 1.65rem; font-weight: 800; color: var(--ww-ink); }}
    [data-testid="stMetricLabel"] {{ font-weight: 650; color: var(--ww-muted); }}
    [data-testid="stMetricDelta"] {{ font-weight: 650; }}
    .ww-sub {{ color: var(--ww-muted); margin-top: -.55rem; margin-bottom: 1.15rem; font-size: .98rem; }}
    .ww-hero {{
        background: linear-gradient(135deg, #062B2B 0%, #075E52 62%, #087F68 100%);
        border-radius: 20px; padding: 1.45rem 1.6rem; margin: 0 0 1.15rem 0;
        box-shadow: 0 12px 30px rgba(6,43,43,.16); color: white;
    }}
    .ww-hero h2 {{ margin: .15rem 0 0; color: white; font-size: 1.7rem; letter-spacing: -.02em; }}
    .ww-hero p {{ margin: .4rem 0 0; color: #D8F4EC; font-size: .95rem; }}
    .ww-pill {{ display:inline-block; padding:.3rem .68rem; border-radius:999px;
        background:rgba(255,255,255,.14); color:#E8FFF8; font-size:.72rem; font-weight:800;
        letter-spacing:.06em; border:1px solid rgba(255,255,255,.16); }}
    .ww-status {{ display:inline-block; margin-left:.45rem; padding:.3rem .68rem; border-radius:999px;
        background:#E7F8F1; color:#087F68; font-size:.72rem; font-weight:800; }}
    .ww-section {{ color: var(--ww-ink); font-weight: 800; letter-spacing: -.01em; }}
    .ww-chat-card {{ background: var(--ww-surface); border:1px solid var(--ww-border); border-radius:16px; padding:1rem 1.1rem; margin:.65rem 0; }}
    .ww-chat-title {{ font-size:1rem; font-weight:750; color:var(--ww-ink); margin-bottom:.2rem; }}
    .ww-chat-muted {{ font-size:.82rem; color:var(--ww-muted); }}
    section[data-testid="stSidebar"] {{ background: linear-gradient(180deg, {THEME['sidebar_bg']} 0%, #0A4440 100%); }}
    section[data-testid="stSidebar"] * {{ color: {THEME['sidebar_ink']}; }}
    section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {{ color:#D8F4EC; }}
    section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {{ color:#BBD9D1; }}
    div[data-testid="stTabs"] button {{ font-weight:700; }}
    div[data-testid="stButton"] button {{ border-radius:11px; font-weight:700; min-height:2.5rem; }}
    div[data-testid="stButton"] button[kind="primary"] {{ background: var(--ww-teal); border-color: var(--ww-teal); color:white; }}
    div[data-testid="stAlert"] {{ border-radius:12px; }}
    div[data-testid="stExpander"] {{ border-color: var(--ww-border); border-radius:12px; }}
    [data-testid="stDataFrame"] {{ border:1px solid var(--ww-border); border-radius:12px; overflow:hidden; }}
    </style>
    """,
    unsafe_allow_html=True,
)

try:
    db.init_db()
except Exception as exc:  # noqa: BLE001 - show a plain-English fix instead of a stack trace
    st.title("WattWise")
    st.error("Could not connect to the database.")
    st.info(db.explain_connection_error(str(exc)))
    st.caption(f"Backend: {db.describe_backend()}")
    st.stop()

ORANGE, BLUE, RED, GREEN = THEME["orange"], THEME["blue"], THEME["red"], THEME["green"]


def inr(value: float) -> str:
    return f"₹{value:,.0f}"


def _company_model_dir(company_id: int) -> str:
    return os.path.join(MODEL_DIR, f"company_{company_id}")


def _valid_hhmm(text: str) -> bool:
    try:
        datetime.strptime(text.strip(), "%H:%M")
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

if "company" not in st.session_state:
    st.session_state.company = None


def _login_screen():
    st.title("⚡ WattWise")
    st.markdown('<p class="ww-sub">Forecast demand, catch peak-load penalties, and cut your electricity bill — built for MSMEs.</p>',
                unsafe_allow_html=True)

    tab_login, tab_signup = st.tabs(["Log in", "New company — sign up"])

    with tab_login:
        api_key = st.text_input("API key", type="password", key="login_key",
                                help="The key shown once when your company was created.")
        if st.button("Log in", type="primary"):
            found = db.get_company_by_api_key(api_key) if api_key else None
            if found is None:
                st.error("Invalid API key.")
            else:
                st.session_state.company = found
                st.rerun()
        st.caption("First time here? Use the sign-up tab, or run `python scripts/bootstrap.py` to create a demo company.")

    with tab_signup:
        with st.form("signup_form"):
            name = st.text_input("Company name")
            c1, c2 = st.columns(2)
            tier = c1.selectbox("Tier", ["micro", "small", "medium"])
            connection_type = c2.selectbox("Connection type", ["LT", "HT"])
            industry_type = st.selectbox(
                "Industry type", ["textile", "plastics", "metal_fabrication", "food_processing", "other"],
                help="Used to tailor the load-shift advice to your process.",
            )
            sanctioned_load = st.number_input("Sanctioned load (kW)", min_value=1.0, value=100.0)
            n_shifts = st.selectbox("Number of shifts", [1, 2, 3])

            default_windows = [("09:00", "17:00"), ("06:00", "14:00"), ("14:00", "22:00")]
            shift_pattern = []
            for i in range(n_shifts):
                col1, col2 = st.columns(2)
                start = col1.text_input(f"Shift {i + 1} start (HH:MM)", value=default_windows[i][0], key=f"shift_start_{i}")
                end = col2.text_input(f"Shift {i + 1} end (HH:MM)", value=default_windows[i][1], key=f"shift_end_{i}")
                shift_pattern.append((start, end))

            submitted = st.form_submit_button("Create company", type="primary")
            if submitted:
                if not name.strip():
                    st.error("Company name is required.")
                elif not all(_valid_hhmm(t) for pair in shift_pattern for t in pair):
                    st.error("Shift times must look like 06:00 or 14:30.")
                else:
                    record = db.CompanyRecord(
                        name=name.strip(), tier=tier, sanctioned_load_kw=sanctioned_load,
                        industry_type=industry_type, shift_pattern=shift_pattern,
                        connection_type=connection_type,
                    )
                    company_id, raw_key = db.create_company(record)
                    st.success(f"Company created (ID {company_id}). Save this API key now — it will not be shown again:")
                    st.code(raw_key)


if st.session_state.company is None:
    _login_screen()
    st.stop()

company = st.session_state.company
company_id = company["id"]
shift_pattern = json.loads(company["shift_pattern_json"]) if company.get("shift_pattern_json") else None
sanctioned_load = company.get("sanctioned_load_kw") or 100.0
industry_type = company.get("industry_type")

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

st.sidebar.markdown(f"### ⚡ {company['name']}")
st.sidebar.caption(
    f"Tier: {company['tier']} · {(industry_type or 'industry not set').replace('_', ' ')} · "
    f"{sanctioned_load:.0f} kW sanctioned"
)

st.sidebar.subheader("1 · Data")
data_mode = st.sidebar.radio("Data source", ["Demo data", "Upload my data"], label_visibility="collapsed")
uploaded = None
scenario = "msme_shift"
if data_mode == "Demo data":
    scenario_labels = {
        "Factory shifts — recommended": "msme_shift",
        "Normal operations": "normal",
        "High-demand stress test": "high_demand",
        "Anomaly detection test": "anomaly_heavy",
    }
    selected_scenario = st.sidebar.selectbox(
        "Demo scenario", list(scenario_labels), index=0,
        help="Choose a prepared scenario to demonstrate forecasting, demand risk, savings, or anomaly detection.",
    )
    scenario = scenario_labels[selected_scenario]

    demo_files = {
        "msme_shift": "01_msme_shift_baseline.csv",
        "normal": "02_normal_operations.csv",
        "high_demand": "03_high_demand_sanctioned_load.csv",
        "anomaly_heavy": "04_anomaly_heavy.csv",
    }
    demo_path = Path(__file__).parent / "demo_data" / demo_files[scenario]
    if demo_path.exists():
        st.sidebar.download_button(
            "Download selected demo CSV",
            data=demo_path.read_bytes(),
            file_name=demo_path.name,
            mime="text/csv",
            width="stretch",
            help="Download the exact dataset used for this prepared scenario. You can upload it again using Upload my data.",
        )
else:
    uploaded = st.sidebar.file_uploader(
        "Upload electricity data (.csv / .txt)", type=["txt", "csv"],
        help="Upload timestamped electricity readings. Supported examples include timestamp + load_kw/power_kw/demand_kw and UCI Date;Time;Global_active_power format.",
    )
    st.sidebar.caption("Files are validated in memory and are not saved under the uploaded filename.")
    st.sidebar.markdown("**Need a sample?**")
    sample_files = [
        "01_msme_shift_baseline.csv", "02_normal_operations.csv",
        "09_food_processing_shift.csv", "10_cold_storage_24x7.csv",
    ]
    sample_dir = Path(__file__).parent / "demo_data"
    for sample_name in sample_files:
        sample_path = sample_dir / sample_name
        if sample_path.exists():
            st.sidebar.download_button(
                f"Download {sample_name.replace('.csv', '')}",
                data=sample_path.read_bytes(),
                file_name=sample_name, mime="text/csv", width="stretch",
            )

st.sidebar.subheader("2 · Forecast")
horizon_hours = st.sidebar.slider("Horizon (hours)", 24, 168, 24, step=24)
shift_fraction = st.sidebar.slider("Shiftable peak load (%)", 0, 100, 30,
                                   help="Share of peak-hour consumption you could realistically move to off-peak.") / 100
ci_level = st.sidebar.selectbox("Confidence interval", [0.8, 0.9, 0.95], index=1, format_func=lambda v: f"{int(v * 100)}%")

run_disabled = data_mode == "Upload my data" and uploaded is None
run_button = st.sidebar.button("Run forecast", type="primary", disabled=run_disabled, width="stretch")
if run_disabled:
    st.sidebar.caption("Upload a file to enable the forecast.")

st.sidebar.divider()
with st.sidebar.expander("Account"):
    if st.button("Rotate API key"):
        new_key = db.rotate_api_key(company_id)
        db.log_audit_event(company_id, action="api_key_rotated")
        st.success("New key generated — save it now:")
        st.code(new_key)
    if st.button("Log out"):
        st.session_state.company = None
        st.session_state.pop("last_run", None)
        st.rerun()
st.sidebar.caption(f"Database: {db.describe_backend().split(':')[0]}")

# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

st.title("WattWise")

if run_button:
    with st.spinner("Loading data, training the model and building the forecast..."):
        try:
            if uploaded is not None:
                load_result = load_from_upload(uploaded.getvalue(), uploaded.name)
                run_scenario = None
            else:
                load_result = load_consumption_data(
                    force_demo=True, scenario=scenario, shift_pattern=shift_pattern,
                    sanctioned_load_kw=sanctioned_load, anchor_to_today=True,
                )
                run_scenario = scenario
            train_result = train_ensemble(
                load_result.df, shift_pattern=shift_pattern, model_dir=_company_model_dir(company_id),
            )

            db.save_training_run(
                company_id=company_id, data_source=load_result.source.value, mae_kw=train_result.mae,
                rmse_kw=train_result.rmse, arima_order=train_result.arima_order,
                rf_weight=train_result.rf_weight, arima_weight=train_result.arima_weight, scenario=run_scenario,
            )

            future = forecast_next_n_hours(load_result.df, train_result, hours=horizon_hours, ci_level=ci_level)
            tariff = TariffWindow()
            flagged = flag_peak_hours(future, tariff)
            flagged = detect_anomalies(flagged, shift_pattern=shift_pattern)
            hist_anomalies = detect_rolling_anomalies(load_result.df, shift_pattern=shift_pattern)
            n_anomalies_historical = int(hist_anomalies["is_anomaly"].sum())

            demand_config = DemandLimitConfig(sanctioned_load_kw=sanctioned_load)
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
                company_id=company_id, source="dashboard", data_source=load_result.source.value,
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
                scenario=run_scenario, profile=company["tier"],
            )
            db.log_audit_event(company_id, action="forecast_run", detail={"run_id": run_id})

            consultant_result = consultant.run_consultant(company_id)
        except (DataLoadError, InsufficientDataError, ValueError) as exc:
            st.error(str(exc))
            st.stop()
        except Exception as exc:  # noqa: BLE001 - never show a raw traceback to the user
            log.exception("Dashboard run failed")
            st.error("Something went wrong while running the forecast.")
            st.info(db.explain_connection_error(str(exc)) if "connect" in str(exc).lower() else str(exc)[:300])
            st.stop()

        st.session_state.last_run = {
            "future": future, "flagged": flagged, "demand_flagged": demand_flagged,
            "demand_summary": demand_summary, "demand_config": demand_config, "savings": savings,
            "recs": recs, "train_result": train_result, "tariff": tariff, "load_result": load_result,
            "n_anomalies_historical": n_anomalies_historical, "consultant_result": consultant_result,
            "ci_level": ci_level, "scenario": run_scenario, "horizon_hours": horizon_hours,
        }

if "last_run" not in st.session_state:
    st.markdown('<p class="ww-sub">Forecast demand, catch peak-load penalties, and see what shifting load would save.</p>',
                unsafe_allow_html=True)
    st.info("👈 Choose your data and settings in the sidebar, then click **Run forecast**.")
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns(4)
        c1.markdown("**1 · Forecast**  \nPredict the next 1–7 days of demand")
        c2.markdown("**2 · Detect**  \nFlag abnormal spikes and limit breaches")
        c3.markdown("**3 · Quantify**  \nEstimate penalty and bill impact in ₹")
        c4.markdown("**4 · Recommend**  \nSuggest what to shift and when")
    st.stop()

run = st.session_state.last_run
future, flagged, demand_flagged = run["future"], run["flagged"], run["demand_flagged"]
demand_summary, demand_config = run["demand_summary"], run["demand_config"]
savings, recs, train_result, tariff = run["savings"], run["recs"], run["train_result"], run["tariff"]
load_result, n_anomalies_historical = run["load_result"], run["n_anomalies_historical"]
consultant_result, run_ci_level, run_scenario = run["consultant_result"], run["ci_level"], run["scenario"]

ci_pct = int(round(run_ci_level * 100))
lower_col, upper_col = f"forecast_kw_lower{ci_pct}", f"forecast_kw_upper{ci_pct}"
limit_kw = demand_config.sanctioned_load_kw
peak_start, peak_end = tariff.peak_hours


# ---------------------------------------------------------------------------
# Chart helpers
# ---------------------------------------------------------------------------

def _style(fig: go.Figure, height: int = 400) -> go.Figure:
    fig.update_layout(
        template=THEME["plot"],
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=THEME["ink"], family="Inter, ui-sans-serif, system-ui, sans-serif"),
        margin=dict(l=10, r=10, t=30, b=10),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    fig.update_xaxes(gridcolor=THEME["grid"], zerolinecolor=THEME["border"])
    fig.update_yaxes(gridcolor=THEME["grid"], zerolinecolor=THEME["border"])
    return fig


def _forecast_figure() -> go.Figure:
    fig = go.Figure()
    hist = load_result.df.tail(48)
    fig.add_trace(go.Scatter(x=hist["datetime"], y=hist["Global_active_power"], name="Recent actual",
                             line=dict(color=BLUE, width=1.5)))
    fig.add_trace(go.Scatter(x=flagged["datetime"], y=flagged[upper_col], line=dict(width=0),
                             showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=flagged["datetime"], y=flagged[lower_col], fill="tonexty",
                             fillcolor="rgba(245,166,35,0.18)", line=dict(width=0), name=f"{ci_pct}% interval",
                             hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=flagged["datetime"], y=flagged["forecast_kw"], name="Forecast",
                             line=dict(color=ORANGE, width=2.5)))
    anomalies = flagged[flagged["is_anomaly"]]
    if len(anomalies):
        fig.add_trace(go.Scatter(x=anomalies["datetime"], y=anomalies["forecast_kw"], mode="markers", name="Anomaly",
                                 marker=dict(color=RED, size=9, symbol="diamond")))
    fig.add_hline(y=limit_kw, line=dict(color=RED, dash="dash"), annotation_text=f"Sanctioned load {limit_kw:.0f} kW",
                  annotation_position="top left")
    days = pd.date_range(hist["datetime"].min().normalize(), flagged["datetime"].max().normalize(), freq="D")
    for day in days:
        fig.add_shape(type="rect", xref="x", yref="paper", layer="below", line_width=0,
                      fillcolor="rgba(255,92,92,0.08)",
                      x0=(day + pd.Timedelta(hours=peak_start)).to_pydatetime(),
                      x1=(day + pd.Timedelta(hours=peak_end)).to_pydatetime(), y0=0, y1=1)
    fig.update_yaxes(title_text="kW")
    return _style(fig, 430)


def _after_shift_profile() -> pd.DataFrame:
    """Hour-of-day average load before vs after shifting: the shifted kWh is spread evenly
    over that day's off-peak hours. Illustrative - assumes the shiftable share really moves."""
    d = savings.detail_df.copy()
    d["date"] = d["datetime"].dt.date
    off = d["tariff_band"] == "Off-Peak"
    per_off_hour = (d.groupby("date")["shifted_kwh"].sum() / d[off].groupby("date").size())
    add = d["date"].map(per_off_hour).fillna(0.0)
    d["after_kw"] = d["optimized_consumption"] + np.where(off, add, 0.0)
    d["hour"] = d["datetime"].dt.hour
    return d.groupby("hour").agg(before=("forecast_kw", "mean"), after=("after_kw", "mean")).reset_index()


def _shift_figure() -> go.Figure:
    prof = _after_shift_profile()
    fig = go.Figure()
    shade = {"Peak": "rgba(255,92,92,0.14)", "Shoulder": "rgba(245,166,35,0.10)", "Off-Peak": "rgba(45,190,140,0.10)"}
    for h in range(24):
        fig.add_shape(type="rect", xref="x", yref="paper", layer="below", line_width=0,
                      fillcolor=shade[tariff.band_for_hour(h)], x0=h, x1=h + 1, y0=0, y1=1)
    fig.add_trace(go.Scatter(x=prof["hour"] + 0.5, y=prof["before"], name="Before: forecast load",
                             line=dict(color=RED, width=3)))
    fig.add_trace(go.Scatter(x=prof["hour"] + 0.5, y=prof["after"], name="After: load shifted",
                             line=dict(color=GREEN, width=3, dash="dash")))
    fig.update_xaxes(title_text=f"Hour of day  ·  peak ₹{tariff.peak_rate:.0f}/kWh, shoulder ₹{tariff.shoulder_rate:.0f}, "
                                f"off-peak ₹{tariff.off_peak_rate:.0f}", range=[0, 24], dtick=3)
    fig.update_yaxes(title_text="Average kW")
    return _style(fig, 380)


# ---------------------------------------------------------------------------
# Header, status banner, KPIs
# ---------------------------------------------------------------------------

st.markdown(
    f'<p class="ww-sub">{company["name"]} · forecast {flagged["datetime"].min():%d %b %H:%M} → '
    f'{flagged["datetime"].max():%d %b %H:%M} ({run["horizon_hours"]} h)'
    + (f' · prepared demonstration data' if run_scenario else ' · your uploaded data') + '</p>',
    unsafe_allow_html=True,
)

if demand_summary.breach_hours > 0:
    first = demand_summary.first_breach_time
    st.error(
        f"**Sanctioned-load breach forecast:** {demand_summary.breach_hours} hour(s) above {limit_kw:.0f} kW"
        + (f", first on {first:%a %d %b at %H:%M}" if first is not None else "")
        + f". Estimated penalty exposure {inr(demand_summary.total_estimated_penalty)}.", icon="🚨")
elif demand_summary.warning_hours > 0:
    st.warning(f"**Close to your limit:** {demand_summary.warning_hours} hour(s) within "
               f"{demand_config.warning_margin_pct:.0f}% of {limit_kw:.0f} kW. Stagger start-ups to stay safe.", icon="⚠️")
else:
    st.success(f"**Within limits:** forecast peak {demand_summary.peak_forecast_kw:.0f} kW against your {limit_kw:.0f} kW sanctioned load.", icon="✅")

kpis = st.columns(5)
kpi_data = [
    ("Peak forecast", f"{demand_summary.peak_forecast_kw:.0f} kW",
     f"{demand_summary.peak_forecast_kw / limit_kw * 100 - 100:+.0f}% vs limit", "inverse"),
    ("Breach / warning hours", f"{demand_summary.breach_hours} / {demand_summary.warning_hours}", None, "off"),
    ("Penalty exposure", inr(demand_summary.total_estimated_penalty), None, "off"),
    ("Est. monthly savings", inr(savings.monthly_savings), f"{savings.savings_pct:.1f}% of bill", "normal"),
    ("Model error (MAE)", f"{train_result.mae:.2f} kW", None, "off"),
]
for col, (label, value, delta, colour) in zip(kpis, kpi_data):
    with col.container(border=True):
        st.metric(label, value, delta=delta, delta_color=colour)

tab_overview, tab_forecast, tab_savings, tab_recs, tab_consultant, tab_whatts, tab_reports = st.tabs(
    ["Overview", "Forecast & Demand Risk", "Savings", "Recommendations", "Consultant", "WhattsOn", "Reports"]
)

with tab_overview:
    st.plotly_chart(_forecast_figure(), width="stretch", config={"displaylogo": False})
    st.caption("Shaded columns are peak-tariff hours. The dashed red line is your sanctioned load.")
    top = [r for r in recs if r.severity.value in ("critical", "warning")] or recs[:2]
    if top:
        st.markdown("**Top actions**")
        for rec in top[:3]:
            st.markdown(f"- {rec.message}")
    st.caption(
        f"Data: {load_result.source.value.replace('_', ' ')} · Ensemble ARIMA{train_result.arima_order} "
        f"(random forest {train_result.rf_weight:.0%}, ARIMA {train_result.arima_weight:.0%})"
    )
    if load_result.quality is not None:
        if load_result.quality.warnings:
            with st.expander(f"Data quality notes ({len(load_result.quality.warnings)})"):
                st.markdown("\n".join(f"- {w}" for w in load_result.quality.warnings))
        else:
            st.caption("✅ Data quality check passed with no warnings.")

with tab_forecast:
    daily = demand_flagged.assign(date=demand_flagged["datetime"].dt.strftime("%a %d %b")).groupby("date", sort=False).agg(
        energy_kwh=("forecast_kw", "sum"), peak_kw=("forecast_kw", "max"), avg_kw=("forecast_kw", "mean"),
        peak_tariff_hours=("is_peak_flag", "sum"),
        breach_hours=("demand_status", lambda s: int((s == "Breach").sum())),
        warning_hours=("demand_status", lambda s: int((s == "Warning").sum())),
    ).reset_index()
    daily["load_factor_pct"] = daily["avg_kw"] / daily["peak_kw"] * 100
    st.subheader("Day by day")
    st.dataframe(
        daily.rename(columns={"date": "Day", "energy_kwh": "Energy (kWh)", "peak_kw": "Peak (kW)", "avg_kw": "Average (kW)",
                              "peak_tariff_hours": "Peak-tariff hrs", "breach_hours": "Breach hrs",
                              "warning_hours": "Warning hrs", "load_factor_pct": "Load factor (%)"}).round(1),
        width="stretch", hide_index=True,
    )
    hist = load_result.df.copy()
    hist["hour"] = hist["datetime"].dt.hour
    prof = hist.groupby("hour")["Global_active_power"].mean().rename("History average")
    fprof = flagged.assign(hour=flagged["datetime"].dt.hour).groupby("hour")["forecast_kw"].mean().rename("Forecast average")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=prof.index, y=prof.values, name="History average", line=dict(color=BLUE, width=2)))
    fig.add_trace(go.Scatter(x=fprof.index, y=fprof.values, name="Forecast average", line=dict(color=ORANGE, width=2.5)))
    fig.update_xaxes(title_text="Hour of day", dtick=3)
    fig.update_yaxes(title_text="Average kW")
    st.subheader("Typical day: history vs forecast")
    st.plotly_chart(_style(fig, 320), width="stretch", config={"displaylogo": False})
    st.subheader("Sanctioned-load risk")
    st.write(f"Contract limit **{limit_kw:.0f} kW** · breach hours **{demand_summary.breach_hours}** · "
             f"estimated penalty **{inr(demand_summary.total_estimated_penalty)}**")
    with st.expander("Hour-by-hour forecast table"):
        st.dataframe(
            demand_flagged[["datetime", "forecast_kw", lower_col, upper_col, "tariff_band", "demand_status", "is_peak_flag", "is_anomaly"]],
            width="stretch", hide_index=True,
        )

with tab_savings:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Baseline cost (horizon)", inr(savings.baseline_cost))
    c2.metric("Optimized cost (horizon)", inr(savings.optimized_cost), delta=f"-{savings.savings_pct:.1f}%", delta_color="inverse")
    c3.metric("Energy shifted", f"{savings.shifted_kwh:,.0f} kWh")
    c4.metric("Projected monthly savings", inr(savings.monthly_savings))
    st.subheader("What shifting load does")
    st.plotly_chart(_shift_figure(), width="stretch", config={"displaylogo": False})
    st.caption(f"Illustrative: assumes {int(round(shift_fraction * 100))}% of peak-hour load can move to off-peak. "
               "Tariffs are configurable defaults, not your actual DISCOM rates.")
    bands = savings.detail_df.groupby("tariff_band").agg(baseline=("baseline_cost", "sum"), optimized=("optimized_cost", "sum")).reindex(
        ["Peak", "Shoulder", "Off-Peak"]).dropna().reset_index()
    fig = go.Figure()
    fig.add_trace(go.Bar(x=bands["tariff_band"], y=bands["baseline"], name="Baseline", marker_color=RED))
    fig.add_trace(go.Bar(x=bands["tariff_band"], y=bands["optimized"], name="Optimized", marker_color=GREEN))
    fig.update_layout(barmode="group")
    fig.update_yaxes(title_text="Cost (₹)")
    st.subheader("Cost by tariff band")
    st.plotly_chart(_style(fig, 300), width="stretch", config={"displaylogo": False})

with tab_recs:
    if not recs:
        st.write("No recommendations for the current run.")
    labels = {"load_shift": "Load shift", "demand_limit": "Demand limit", "anomaly": "Anomaly", "general": "General"}
    for rec in recs:
        body = f"**{labels.get(rec.category.value, rec.category.value)}** — {rec.message}" + ("  \n_Could be automated._" if rec.automatable else "")
        if rec.severity.value == "critical":
            st.error(body, icon="🔴")
        elif rec.severity.value == "warning":
            st.warning(body, icon="🟠")
        else:
            st.info(body, icon="🔵")

with tab_consultant:
    st.subheader("Trending (this week vs. last)")
    if consultant_result["trending"]:
        for note in consultant_result["trending"]:
            st.write(f"- {note['message']}")
    else:
        st.caption("Not enough run history yet for a trend — check back after a few more forecasts.")

    st.subheader("Strategic (structural)")
    if consultant_result["strategic"]:
        for note in consultant_result["strategic"]:
            st.write(f"- {note['message']}")
    else:
        st.caption("No structural recommendations at this time.")

with tab_whatts:
    st.markdown(
        """
        <div class="ww-hero">
            <span class="ww-pill">ENERGY INTELLIGENCE</span>
            <h2>WhattsOn</h2>
            <p>Ask about your forecast, cost, sanctioned-load risk, anomalies and operational recommendations.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    whatts_context = context_from_run(
        company_name=company["name"],
        industry=industry_type,
        sanctioned_load_kw=sanctioned_load,
        run=run,
    )

    if "whatts_on_messages" not in st.session_state:
        st.session_state.whatts_on_messages = []

    st.markdown("**Try a question**")
    q1, q2, q3, q4 = st.columns(4)
    quick_questions = [
        (q1, "Forecast", "What is my forecast for tomorrow?"),
        (q2, "Risk", "Will I exceed my sanctioned load?"),
        (q3, "Savings", "How much can I save by shifting production?"),
        (q4, "Accuracy", "What is the model accuracy?"),
    ]

    selected_question = None
    for col, label, value in quick_questions:
        if col.button(label, key=f"whatts_quick_{label.lower()}", width="stretch"):
            selected_question = value

    for msg in st.session_state.whatts_on_messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    question = st.chat_input(
        "Ask WhattsOn about your energy, forecast or savings…",
        key="whatts_on_input",
    )

    if selected_question:
        question = selected_question

    if question:
        st.session_state.whatts_on_messages.append(
            {"role": "user", "content": question}
        )
        response = whatts_on_answer(question, whatts_context)
        st.session_state.whatts_on_messages.append(
            {"role": "assistant", "content": response}
        )
        db.log_audit_event(
            company_id,
            action="whatts_on_question",
        )
        st.rerun()

with tab_reports:
    if "reports" not in run:  # build once per run, not on every widget interaction
        peak_idx = future["forecast_kw"].idxmax()
        forecast_ci = (float(future.loc[peak_idx, lower_col]), float(future.loc[peak_idx, upper_col]), ci_pct)
        common = dict(
            data_source=load_result.source.value, scenario=run_scenario, tariff=tariff,
            demand_config=demand_config, demand_summary=demand_summary,
            savings_baseline=savings.baseline_cost, savings_optimized=savings.optimized_cost,
            savings_pct=savings.savings_pct, monthly_savings_est=savings.monthly_savings,
            n_peak_hours=int(flagged["is_peak_flag"].sum()), n_anomalies_forecast=int(flagged["is_anomaly"].sum()),
            n_anomalies_historical=n_anomalies_historical, model_mae=train_result.mae, model_rmse=train_result.rmse,
            arima_order=train_result.arima_order, rf_weight=train_result.rf_weight, recommendations=recs,
            forecast_ci=forecast_ci, consultant_notes=consultant_result,
        )
        run["reports"] = {
            "md": build_summary_report(**common),
            "pdf": build_pdf_report(
                **common, predicted_peak_kw=float(future["forecast_kw"].max()),
                predicted_peak_time=str(future.loc[peak_idx, "datetime"]),
                predicted_avg_kw=float(future["forecast_kw"].mean()),
                predicted_total_kwh=float(future["forecast_kw"].sum()),
            ),
        }
    st.write("Download this run as a report to share with your team or facility manager.")
    d1, d2 = st.columns(2)
    d1.download_button("Download PDF report", run["reports"]["pdf"], file_name="wattwise_report.pdf",
                       mime="application/pdf", type="primary", width="stretch")
    d2.download_button("Download Markdown report", run["reports"]["md"], file_name="wattwise_report.md", width="stretch")
