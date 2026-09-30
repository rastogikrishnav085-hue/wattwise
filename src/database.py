"""
database.py
------------
Persistence layer — multi-tenant, and now backend-agnostic via
SQLAlchemy Core instead of raw sqlite3.

Why this changed: the original SQLite version is genuinely the right
choice for a single-machine demo (matches start_wattwise.sh/.bat, zero
setup, zero cost). But it does not work at all on free hosts like
Streamlit Community Cloud or Render's free tier — their filesystems are
ephemeral or not shared between services, so a SQLite file would vanish
or diverge between the dashboard and the API the moment they're deployed
as two separate public services. Postgres (e.g. a free Supabase project)
is a real network service both can reach identically.

This module still defaults to SQLite with zero configuration (nothing
breaks locally, nothing breaks in the test suite). Setting the
DATABASE_URL environment variable to a Postgres connection string (what
Supabase gives you) switches the backend with NO other code changes —
every function still takes the same db_path parameter it always did, for
backward compatibility and so tests can still point at an isolated temp
file. A bare filesystem path (what every existing caller and test passes)
is still interpreted as "a SQLite file at this path" automatically.

Every query is still scoped by company_id.
"""

from __future__ import annotations
import hashlib
import json
import os
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    create_engine, event, MetaData, Table, Column,
    Integer, Float, String, Text, Boolean, ForeignKey,
    select, insert, update, delete, func,
)
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.pool import NullPool

from .config import BASE_DIR, DATABASE_URL as DEFAULT_DATABASE_URL
from .features import validate_shift_pattern
from .logging_setup import get_logger

log = get_logger(__name__)

# Kept for anything that still references the old constant name/shape —
# it's now just the default connection string, not a hardcoded file path.
DB_PATH = DEFAULT_DATABASE_URL

metadata = MetaData()

companies = Table(
    "companies", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(255), nullable=False),
    Column("tier", String(20), nullable=False),
    Column("industry_type", String(100)),
    Column("shift_pattern_json", Text),
    Column("sanctioned_load_kw", Float),
    Column("connection_type", String(10)),
    Column("api_key_hash", String(128), nullable=False, unique=True),
    Column("created_at", String(64), nullable=False),
)

users = Table(
    "users", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("company_id", Integer, ForeignKey("companies.id"), nullable=False),
    Column("email", String(255), nullable=False, unique=True),
    Column("password_hash", String(255), nullable=False),
    Column("password_salt", String(64), nullable=False),
    Column("role", String(20), nullable=False, server_default="owner"),
    Column("created_at", String(64), nullable=False),
)

training_runs = Table(
    "training_runs", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("company_id", Integer, ForeignKey("companies.id"), nullable=False),
    Column("trained_at_utc", String(64), nullable=False),
    Column("data_source", String(64), nullable=False),
    Column("scenario", String(64)),
    Column("mae_kw", Float, nullable=False),
    Column("rmse_kw", Float, nullable=False),
    Column("arima_order", Text, nullable=False),
    Column("rf_weight", Float, nullable=False),
    Column("arima_weight", Float, nullable=False),
)

forecast_runs = Table(
    "forecast_runs", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("company_id", Integer, ForeignKey("companies.id"), nullable=False),
    Column("saved_at_utc", String(64), nullable=False),
    Column("source", String(20), nullable=False),
    Column("data_source", String(64), nullable=False),
    Column("scenario", String(64)),
    Column("horizon_hours", Integer, nullable=False),
    Column("profile", String(20)),
    Column("peak_hours_flagged", Integer, nullable=False),
    Column("anomalies_forecast", Integer, nullable=False),
    Column("anomalies_historical", Integer, nullable=False),
    Column("demand_breach_hours", Integer, nullable=False),
    Column("demand_warning_hours", Integer, nullable=False),
    Column("estimated_penalty", Float, nullable=False),
    Column("baseline_cost", Float, nullable=False),
    Column("optimized_cost", Float, nullable=False),
    Column("savings_pct", Float, nullable=False),
    Column("monthly_savings_est", Float, nullable=False),
    Column("model_mae_kw", Float, nullable=False),
)

recommendations_log = Table(
    "recommendations_log", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("forecast_run_id", Integer, ForeignKey("forecast_runs.id"), nullable=False),
    Column("category", String(64), nullable=False),
    Column("severity", String(20), nullable=False),
    Column("message", Text, nullable=False),
    Column("automatable", Boolean, nullable=False),
)

consultant_notes = Table(
    "consultant_notes", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("company_id", Integer, ForeignKey("companies.id"), nullable=False),
    Column("created_at_utc", String(64), nullable=False),
    Column("tier", String(20), nullable=False),
    Column("category", String(64), nullable=False),
    Column("message", Text, nullable=False),
    Column("trend_direction", String(20)),
    Column("acknowledged", Boolean, nullable=False, server_default="false"),
)

audit_log = Table(
    "audit_log", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("company_id", Integer, ForeignKey("companies.id"), nullable=False),
    Column("actor_user_id", Integer, ForeignKey("users.id")),
    Column("action", String(100), nullable=False),
    Column("detail_json", Text),
    Column("ip_address", String(64)),
    Column("created_at_utc", String(64), nullable=False),
)


# ---------------------------------------------------------------------------
# Engine resolution — the one place backend choice happens
# ---------------------------------------------------------------------------

_ENGINE_CACHE: dict[str, Engine] = {}
_SCHEMA_ENSURED: set[int] = set()
_CACHE_LOCK = threading.Lock()


def _normalize_url(db_path: Optional[str]) -> str:
    url = db_path or DEFAULT_DATABASE_URL
    if url.startswith("postgres://"):
        # Supabase/Heroku-style URLs use the old "postgres://" scheme;
        # SQLAlchemy 2.x requires "postgresql://".
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        # Pin the driver explicitly. Without this, newer SQLAlchemy versions default
        # "postgresql://" to the psycopg (v3) driver, which isn't what requirements.txt
        # installs (psycopg2-binary) — every Postgres/Supabase URL would fail on first
        # connect with "No module named 'psycopg'".
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    if not (url.startswith("postgresql+psycopg2://") or url.startswith("sqlite://")):
        # A bare filesystem path (every existing caller/test passes this) —
        # treat it as "a SQLite file at this path", same as before.
        url = f"sqlite:///{url}"
    return url


def _resolve_engine(db_path: Optional[str]) -> Engine:
    url = _normalize_url(db_path)
    with _CACHE_LOCK:
        engine = _ENGINE_CACHE.get(url)
        if engine is None:
            if url.startswith("sqlite"):
                # sqlite:///<path> — ensure the parent directory exists (the old
                # code did this via get_connection's os.makedirs call).
                raw_path = url.replace("sqlite:///", "", 1)
                if raw_path and raw_path != ":memory:":
                    os.makedirs(os.path.dirname(raw_path) or ".", exist_ok=True)
                # NullPool: closes the underlying sqlite3 connection the instant each
                # `with engine.begin()` block exits, instead of keeping it parked in a
                # pool. Without this, Windows keeps the .db file locked open even after
                # a test is done with it — os.remove() then fails with
                # "PermissionError: [WinError 32] ... used by another process". Linux
                # doesn't enforce that lock, which is why this only ever showed up on
                # Windows, not in this project's own Linux-based testing.
                engine = create_engine(
                    url, connect_args={"check_same_thread": False}, future=True, poolclass=NullPool,
                )

                @event.listens_for(engine, "connect")
                def _enforce_sqlite_foreign_keys(dbapi_connection, connection_record):
                    cursor = dbapi_connection.cursor()
                    cursor.execute("PRAGMA foreign_keys=ON")
                    cursor.close()
            else:
                # Small pool on purpose: free Supabase tiers cap concurrent connections, and both
                # the dashboard and the API each open their own pool against the same database.
                engine = create_engine(
                    url, future=True, pool_pre_ping=True,
                    pool_size=3, max_overflow=2, pool_recycle=300,
                )
            _ENGINE_CACHE[url] = engine

        if id(engine) not in _SCHEMA_ENSURED:
            metadata.create_all(engine)
            _SCHEMA_ENSURED.add(id(engine))

        return engine


def explain_connection_error(message: str) -> str:
    """Turns a raw database/driver error into one plain-English next step."""
    m = (message or "").lower()
    if "your-password" in m or "placeholder" in m:
        return "The [YOUR-PASSWORD] placeholder is still in DATABASE_URL. Replace it (brackets included) with your real password."
    if "could not translate host name" in m or "name or service not known" in m or "nodename nor servname" in m:
        return ("The database host can't be found. Either the URL has a typo, or you used Supabase's 'Direct connection' "
                "(IPv6-only). In Supabase click Connect and copy the 'Session pooler' string instead.")
    if "network is unreachable" in m or "cannot assign requested address" in m:
        return "Your network can't reach that address (an IPv6-only 'Direct connection'). Use Supabase's 'Session pooler' string."
    if "tenant or user not found" in m:
        return "The username must be 'postgres.<project-ref>' (with the dot and project ref), exactly as Supabase shows it."
    if "password authentication failed" in m:
        return ("Wrong password (or username). Reset it in Supabase > Project Settings > Database, use letters and numbers "
                "only, then update DATABASE_URL everywhere it is set.")
    if "timeout" in m or "timed out" in m:
        return ("Timed out. A free Supabase project pauses after inactivity - open the Supabase dashboard and click "
                "'Restore project', then retry. Also check your internet connection.")
    if "no module named 'psycopg2'" in m:
        return "The Postgres driver isn't installed. Run:  pip install psycopg2-binary"
    if "ssl" in m:
        return "TLS/SSL problem. Use the Supabase pooler string exactly as given and don't edit the host."
    return "Check DATABASE_URL: the most common causes are a wrong password or using the Direct connection instead of the Session pooler."


def describe_backend(db_path: Optional[str] = None) -> str:
    """Human-readable backend name that never includes a password."""
    url = _normalize_url(db_path)
    if url.startswith("sqlite"):
        return "SQLite file: " + url.replace("sqlite:///", "", 1)
    return "PostgreSQL (Supabase): " + make_url(url).render_as_string(hide_password=True).split("@")[-1]


def init_db(db_path: Optional[str] = None) -> None:
    """Explicitly ensure the schema exists — safe to call repeatedly."""
    _resolve_engine(db_path)
    log.info("Database ready - %s", describe_backend(db_path))



def reset_database(db_path: Optional[str] = None) -> str:
    """Destructively reset the WattWise application database and recreate the schema.

    This is intended for local/SIH demo resets. It removes all tenants, users,
    forecast/training history, recommendations, consultant notes, and audit logs.
    The schema itself is preserved. Returns a human-readable backend description.
    """
    engine = _resolve_engine(db_path)
    with engine.begin() as conn:
        # Delete children before parents for both SQLite and PostgreSQL FK rules.
        conn.execute(delete(recommendations_log))
        conn.execute(delete(audit_log))
        conn.execute(delete(consultant_notes))
        conn.execute(delete(forecast_runs))
        conn.execute(delete(training_runs))
        conn.execute(delete(users))
        conn.execute(delete(companies))
    log.info("Database reset - %s", describe_backend(db_path))
    return describe_backend(db_path)

def count_companies(db_path: Optional[str] = None) -> int:
    """Used by scripts/bootstrap.py to decide whether to create a demo company."""
    engine = _resolve_engine(db_path)
    with engine.begin() as conn:
        return int(conn.execute(select(func.count()).select_from(companies)).scalar())


def dispose_engine(db_path: Optional[str] = None) -> None:
    """Closes and forgets the cached engine for this db_path. Mainly for tests that
    need to physically delete a SQLite file right after using it — on Windows, an
    engine's pool can keep the file locked open even between uses without this."""
    url = _normalize_url(db_path)
    with _CACHE_LOCK:
        engine = _ENGINE_CACHE.pop(url, None)
        if engine is not None:
            engine.dispose()
            _SCHEMA_ENSURED.discard(id(engine))


# ---------------------------------------------------------------------------
# Auth primitives — unchanged (pure Python, no DB access)
# ---------------------------------------------------------------------------

def _hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return digest.hex(), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    computed, _ = _hash_password(password, salt)
    return secrets.compare_digest(computed, password_hash)


def _hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_api_key() -> str:
    """Returns a new raw API key. Caller shows this to the user ONCE and stores only its hash."""
    return f"wwk_{secrets.token_urlsafe(32)}"


# ---------------------------------------------------------------------------
# Companies
# ---------------------------------------------------------------------------

@dataclass
class CompanyRecord:
    name: str
    tier: str
    sanctioned_load_kw: float
    industry_type: Optional[str] = None
    shift_pattern: Optional[list] = None
    connection_type: Optional[str] = None


def create_company(record: CompanyRecord, db_path: Optional[str] = None) -> tuple[int, str]:
    """Creates a company and returns (company_id, raw_api_key) — the raw key is returned
    exactly once; only its hash is persisted."""
    if record.tier not in ("micro", "small", "medium"):
        raise ValueError("tier must be one of: micro, small, medium")
    if record.sanctioned_load_kw is not None and record.sanctioned_load_kw <= 0:
        raise ValueError("sanctioned_load_kw must be positive")
    validate_shift_pattern(record.shift_pattern)

    raw_key = generate_api_key()
    key_hash = _hash_api_key(raw_key)
    engine = _resolve_engine(db_path)

    with engine.begin() as conn:
        result = conn.execute(
            insert(companies).values(
                name=record.name, tier=record.tier, industry_type=record.industry_type,
                shift_pattern_json=json.dumps(record.shift_pattern) if record.shift_pattern else None,
                sanctioned_load_kw=record.sanctioned_load_kw, connection_type=record.connection_type,
                api_key_hash=key_hash, created_at=datetime.now(timezone.utc).isoformat(),
            )
        )
        company_id = result.inserted_primary_key[0]

    log.info("Created company #%s (%s)", company_id, record.name)
    return company_id, raw_key


def get_company_by_api_key(raw_key: str, db_path: Optional[str] = None) -> Optional[dict]:
    # Copy-pasting a key very often drags along a trailing space/newline or wrapping quotes;
    # real keys never contain any of those, so trimming them can't make a wrong key match.
    raw_key = (raw_key or "").strip().strip("\"'").strip()
    if not raw_key:
        return None
    key_hash = _hash_api_key(raw_key)
    engine = _resolve_engine(db_path)
    with engine.begin() as conn:
        row = conn.execute(select(companies).where(companies.c.api_key_hash == key_hash)).mappings().first()
        return dict(row) if row else None


def get_company(company_id: int, db_path: Optional[str] = None) -> Optional[dict]:
    engine = _resolve_engine(db_path)
    with engine.begin() as conn:
        row = conn.execute(select(companies).where(companies.c.id == company_id)).mappings().first()
        return dict(row) if row else None


def rotate_api_key(company_id: int, db_path: Optional[str] = None) -> str:
    raw_key = generate_api_key()
    key_hash = _hash_api_key(raw_key)
    engine = _resolve_engine(db_path)
    with engine.begin() as conn:
        conn.execute(update(companies).where(companies.c.id == company_id).values(api_key_hash=key_hash))
    log.info("Rotated API key for company #%s", company_id)
    return raw_key


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def create_user(company_id: int, email: str, password: str, role: str = "owner", db_path: Optional[str] = None) -> int:
    if role not in ("owner", "manager", "viewer"):
        raise ValueError("role must be one of: owner, manager, viewer")
    password_hash, salt = _hash_password(password)
    engine = _resolve_engine(db_path)
    with engine.begin() as conn:
        result = conn.execute(
            insert(users).values(
                company_id=company_id, email=email, password_hash=password_hash,
                password_salt=salt, role=role, created_at=datetime.now(timezone.utc).isoformat(),
            )
        )
        return result.inserted_primary_key[0]


def get_user_by_email(email: str, db_path: Optional[str] = None) -> Optional[dict]:
    engine = _resolve_engine(db_path)
    with engine.begin() as conn:
        row = conn.execute(select(users).where(users.c.email == email)).mappings().first()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Training runs
# ---------------------------------------------------------------------------

def save_training_run(
    company_id: int, data_source: str, mae_kw: float, rmse_kw: float, arima_order: tuple,
    rf_weight: float, arima_weight: float, scenario: Optional[str] = None, db_path: Optional[str] = None,
) -> int:
    engine = _resolve_engine(db_path)
    with engine.begin() as conn:
        result = conn.execute(
            insert(training_runs).values(
                company_id=company_id, trained_at_utc=datetime.now(timezone.utc).isoformat(),
                data_source=data_source, scenario=scenario, mae_kw=mae_kw, rmse_kw=rmse_kw,
                arima_order=json.dumps(list(arima_order)), rf_weight=rf_weight, arima_weight=arima_weight,
            )
        )
        return result.inserted_primary_key[0]


def get_recent_training_runs(company_id: int, limit: int = 20, db_path: Optional[str] = None) -> list[dict]:
    engine = _resolve_engine(db_path)
    with engine.begin() as conn:
        rows = conn.execute(
            select(training_runs).where(training_runs.c.company_id == company_id)
            .order_by(training_runs.c.trained_at_utc.desc()).limit(limit)
        ).mappings().all()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Forecast runs + recommendations
# ---------------------------------------------------------------------------

@dataclass
class RecommendationRecord:
    category: str
    severity: str
    message: str
    automatable: bool


def save_forecast_run(
    company_id: int, source: str, data_source: str, horizon_hours: int,
    peak_hours_flagged: int, anomalies_forecast: int, anomalies_historical: int,
    demand_breach_hours: int, demand_warning_hours: int, estimated_penalty: float,
    baseline_cost: float, optimized_cost: float, savings_pct: float, monthly_savings_est: float,
    model_mae_kw: float, recommendations: list[RecommendationRecord],
    scenario: Optional[str] = None, profile: Optional[str] = None, db_path: Optional[str] = None,
) -> int:
    engine = _resolve_engine(db_path)
    with engine.begin() as conn:
        result = conn.execute(
            insert(forecast_runs).values(
                company_id=company_id, saved_at_utc=datetime.now(timezone.utc).isoformat(), source=source,
                data_source=data_source, scenario=scenario, horizon_hours=horizon_hours, profile=profile,
                peak_hours_flagged=peak_hours_flagged, anomalies_forecast=anomalies_forecast,
                anomalies_historical=anomalies_historical, demand_breach_hours=demand_breach_hours,
                demand_warning_hours=demand_warning_hours, estimated_penalty=estimated_penalty,
                baseline_cost=baseline_cost, optimized_cost=optimized_cost, savings_pct=savings_pct,
                monthly_savings_est=monthly_savings_est, model_mae_kw=model_mae_kw,
            )
        )
        forecast_run_id = result.inserted_primary_key[0]

        for rec in recommendations:
            conn.execute(
                insert(recommendations_log).values(
                    forecast_run_id=forecast_run_id, category=rec.category, severity=rec.severity,
                    message=rec.message, automatable=bool(rec.automatable),
                )
            )

    log.info(
        "Saved forecast run #%s for company #%s (source=%s, %s recommendations)",
        forecast_run_id, company_id, source, len(recommendations),
    )
    return forecast_run_id


def get_recent_forecast_runs(company_id: int, limit: int = 20, db_path: Optional[str] = None) -> list[dict]:
    engine = _resolve_engine(db_path)
    with engine.begin() as conn:
        rows = conn.execute(
            select(forecast_runs).where(forecast_runs.c.company_id == company_id)
            .order_by(forecast_runs.c.saved_at_utc.desc()).limit(limit)
        ).mappings().all()
        return [dict(r) for r in rows]


def get_recommendations_for_run(forecast_run_id: int, company_id: int, db_path: Optional[str] = None) -> list[dict]:
    """company_id is required and checked so one tenant can't pull another's recommendations
    by guessing a forecast_run_id."""
    engine = _resolve_engine(db_path)
    with engine.begin() as conn:
        owner = conn.execute(
            select(forecast_runs.c.company_id).where(forecast_runs.c.id == forecast_run_id)
        ).first()
        if owner is None or owner[0] != company_id:
            return []
        rows = conn.execute(
            select(recommendations_log).where(recommendations_log.c.forecast_run_id == forecast_run_id)
            .order_by(recommendations_log.c.id)
        ).mappings().all()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Consultant notes
# ---------------------------------------------------------------------------

def save_consultant_note(
    company_id: int, tier: str, category: str, message: str,
    trend_direction: Optional[str] = None, db_path: Optional[str] = None,
) -> int:
    if tier not in ("immediate", "trending", "strategic"):
        raise ValueError("tier must be one of: immediate, trending, strategic")
    engine = _resolve_engine(db_path)
    with engine.begin() as conn:
        result = conn.execute(
            insert(consultant_notes).values(
                company_id=company_id, created_at_utc=datetime.now(timezone.utc).isoformat(),
                tier=tier, category=category, message=message,
                trend_direction=trend_direction, acknowledged=False,
            )
        )
        return result.inserted_primary_key[0]


def get_consultant_notes(
    company_id: int, tier: Optional[str] = None, limit: int = 50, db_path: Optional[str] = None,
) -> list[dict]:
    engine = _resolve_engine(db_path)
    stmt = select(consultant_notes).where(consultant_notes.c.company_id == company_id)
    if tier:
        stmt = stmt.where(consultant_notes.c.tier == tier)
    stmt = stmt.order_by(consultant_notes.c.created_at_utc.desc()).limit(limit)
    with engine.begin() as conn:
        rows = conn.execute(stmt).mappings().all()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def log_audit_event(
    company_id: int, action: str, actor_user_id: Optional[int] = None,
    detail: Optional[dict] = None, ip_address: Optional[str] = None, db_path: Optional[str] = None,
) -> int:
    engine = _resolve_engine(db_path)
    with engine.begin() as conn:
        result = conn.execute(
            insert(audit_log).values(
                company_id=company_id, actor_user_id=actor_user_id, action=action,
                detail_json=json.dumps(detail) if detail else None, ip_address=ip_address,
                created_at_utc=datetime.now(timezone.utc).isoformat(),
            )
        )
        return result.inserted_primary_key[0]


def get_audit_log(company_id: int, limit: int = 100, db_path: Optional[str] = None) -> list[dict]:
    engine = _resolve_engine(db_path)
    with engine.begin() as conn:
        rows = conn.execute(
            select(audit_log).where(audit_log.c.company_id == company_id)
            .order_by(audit_log.c.created_at_utc.desc()).limit(limit)
        ).mappings().all()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------

def clear_company_data(company_id: int, db_path: Optional[str] = None) -> None:
    """Wipes one company's rows only (schema stays, other tenants untouched)."""
    engine = _resolve_engine(db_path)
    with engine.begin() as conn:
        run_ids = [
            r[0] for r in conn.execute(
                select(forecast_runs.c.id).where(forecast_runs.c.company_id == company_id)
            ).all()
        ]
        if run_ids:
            conn.execute(delete(recommendations_log).where(recommendations_log.c.forecast_run_id.in_(run_ids)))
        conn.execute(delete(forecast_runs).where(forecast_runs.c.company_id == company_id))
        conn.execute(delete(training_runs).where(training_runs.c.company_id == company_id))
        conn.execute(delete(consultant_notes).where(consultant_notes.c.company_id == company_id))
        conn.execute(delete(audit_log).where(audit_log.c.company_id == company_id))
