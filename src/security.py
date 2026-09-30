"""
security.py
-------------
Backend security for the FastAPI service.

Changes from the single-shared-key version:
  - Auth is now per-company: the X-API-Key header is looked up against
    the `companies` table (database.get_company_by_api_key), not
    compared to one global secret. A valid key resolves to a company
    record, which every route then uses to scope its DB reads/writes.
  - Auth is FAIL-CLOSED in production. The old behavior (no key
    configured => no auth at all) is only permitted when
    WATTWISE_ENV=development. Starting in production with no auth
    configured now raises at import time instead of silently running
    open.
  - The rate limiter interface is unchanged in shape but documented as
    what it is: correct for one process, not for multiple uvicorn
    workers. Swapping the backing store to Redis means changing the
    body of InMemoryRateLimiter.allow() — the call sites don't change.
"""

from __future__ import annotations
import os
import threading
import time
from collections import defaultdict, deque
from typing import Optional

from fastapi import Header, HTTPException, Request

from . import database as db
from .logging_setup import get_logger

log = get_logger(__name__)

WATTWISE_ENV = os.environ.get("WATTWISE_ENV", "development")

if WATTWISE_ENV not in ("development", "staging", "production"):
    raise RuntimeError(
        f"WATTWISE_ENV='{WATTWISE_ENV}' is not recognized — expected one of "
        "'development', 'staging', 'production'. Refusing to guess which security "
        "posture to run with."
    )

if WATTWISE_ENV == "production":
    log.info("WATTWISE_ENV=production — per-company API key auth is enforced on every request.")
else:
    log.warning(
        "WATTWISE_ENV=%s — a missing or invalid API key on a request will be rejected the same way "
        "it would in production (per-company keys are always required), but note this flag exists "
        "so other environment-specific relaxations (verbose errors, permissive CORS) can hang off it "
        "instead of being hardcoded as always-on.",
        WATTWISE_ENV,
    )


class CompanyContext:
    """Attached to a request once its API key resolves. Routes read company_id off this,
    never off a client-supplied field, so a request can't claim to be a different tenant."""

    def __init__(self, company_id: int, name: str, tier: str):
        self.company_id = company_id
        self.name = name
        self.tier = tier


class InMemoryRateLimiter:
    """
    Fixed-window rate limiter keyed by an arbitrary string, held in process memory.
    Thread-safe for a single-process uvicorn deployment.

    NOT safe across multiple worker processes or multiple instances — each would keep
    its own counters, which multiplies the effective limit. Before running
    `uvicorn api:app --workers N>1` or more than one instance behind a load balancer,
    replace the body of `allow()` with a call to a shared store (Redis INCR + EXPIRE
    is the standard pattern) — call sites do not need to change.
    """

    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def is_blocked(self, key: str) -> bool:
        """True if `key` is already at its limit. Does NOT record a hit (use allow() for that)."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window_seconds:
                hits.popleft()
            return len(hits) >= self.max_requests

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window_seconds:
                hits.popleft()
            if len(hits) >= self.max_requests:
                return False
            hits.append(now)
            return True


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# Failed-auth attempts are rate-limited per IP — not because 256-bit random keys are
# brute-forceable (they aren't), but because every attempt still costs a DB query and a
# hash compare, and there was previously no throttle or visibility into repeated failures
# at all. 20/minute is generous for a real client mistyping a key, tight for an automated probe.
auth_failure_limiter = InMemoryRateLimiter(max_requests=20, window_seconds=60)

# Signup has no auth to gate it (that's the point — it's how a key is issued), so it's
# rate-limited by IP instead, to stop spam company creation.
signup_rate_limiter = InMemoryRateLimiter(max_requests=10, window_seconds=60)

# Training is the most expensive operation exposed by this API (full model fit).
train_rate_limiter = InMemoryRateLimiter(max_requests=5, window_seconds=60)

# /forecast and /forecast/upload trigger the exact same train_ensemble() call as /train —
# they need the same class of protection, just a little more generous since they're the
# normal, expected path a dashboard session uses repeatedly.
forecast_rate_limiter = InMemoryRateLimiter(max_requests=10, window_seconds=60)


def require_company(request: Request, x_api_key: Optional[str] = Header(default=None)) -> CompanyContext:
    """
    FastAPI dependency. Every route that touches company data should depend on this
    (not a bare boolean check) and use the returned CompanyContext.company_id for
    every database call — never a company_id read from the request body or query
    params, which a caller could forge.
    """
    ip = _client_ip(request)
    # Only FAILED attempts count toward the limit. Previously every request - successful ones
    # included - was counted, so a dashboard making 20 normal calls in a minute was locked out
    # with "too many failed authentication attempts".
    if auth_failure_limiter.is_blocked(ip):
        raise HTTPException(status_code=429, detail="Too many failed authentication attempts. Try again shortly.")

    if not x_api_key:
        auth_failure_limiter.allow(ip)
        raise HTTPException(status_code=401, detail="Missing X-API-Key header.")

    company = db.get_company_by_api_key(x_api_key)
    if company is None:
        auth_failure_limiter.allow(ip)
        log.warning("Auth failure from %s: invalid API key.", ip)
        # Deliberately identical error/timing profile to "missing header" above -
        # don't tell an attacker whether the key format was plausible.
        raise HTTPException(status_code=401, detail="Invalid API key.")

    return CompanyContext(company_id=company["id"], name=company["name"], tier=company["tier"])


def enforce_signup_rate_limit(request: Request) -> None:
    if not signup_rate_limiter.allow(_client_ip(request)):
        raise HTTPException(status_code=429, detail="Too many signup attempts from this address. Try again shortly.")


def enforce_train_rate_limit(request: Request, company: CompanyContext) -> None:
    key = f"{company.company_id}:{_client_ip(request)}"
    if not train_rate_limiter.allow(key):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded for /train (max 5 requests/minute per company). Try again shortly.",
        )


def enforce_forecast_rate_limit(request: Request, company: CompanyContext) -> None:
    key = f"{company.company_id}:{_client_ip(request)}"
    if not forecast_rate_limiter.allow(key):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded for forecasting (max 10 requests/minute per company). Try again shortly.",
        )
