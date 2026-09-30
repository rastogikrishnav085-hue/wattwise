"""
scripts/bootstrap.py
----------------------
One-time setup: ensures the database schema exists and, if no company has
been created yet, creates a default demo company so there's something to
log into on first run. Safe to run every startup — it only creates a
company the very first time (when the companies table is empty).
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import database as db


def main() -> None:
    try:
        db.init_db()
        existing = db.count_companies()
    except Exception as exc:  # noqa: BLE001 - explain instead of showing a stack trace
        print("\n[FAILED] Could not connect to the database.")
        print(f"What to do: {db.explain_connection_error(str(exc))}")
        print("Then run:   python scripts/check_database.py")
        sys.exit(1)

    if existing > 0:
        print(f"[OK] {existing} compan{'y' if existing == 1 else 'ies'} already registered — skipping demo company creation.")
        return

    record = db.CompanyRecord(
        name="Demo MSME",
        tier="small",
        sanctioned_load_kw=100.0,
        industry_type="textile",
        shift_pattern=[("06:00", "14:00"), ("14:00", "22:00")],
        connection_type="LT",
    )
    company_id, raw_key = db.create_company(record)

    print("")
    print("============================================")
    print(" First-time setup: demo company created")
    print("============================================")
    print(f" Company ID : {company_id}")
    print(f" API key    : {raw_key}")
    print("")
    print(" SAVE THIS KEY — it will not be shown again.")
    print(" Use it to log in on the dashboard (http://localhost:8501),")
    print(" or as the X-API-Key header when calling the API directly")
    print(" (http://localhost:8000/docs).")
    print("============================================")
    print("")


if __name__ == "__main__":
    main()
