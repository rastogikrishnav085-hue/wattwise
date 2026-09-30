"""
scripts/check_database.py
--------------------------
Run this once after setting DATABASE_URL (e.g. your Supabase Session pooler string):

    python scripts/check_database.py

It connects, creates the tables if they don't exist, and prints a plain-English
next step if anything is wrong. It never prints your password.
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from src import database as db


def main() -> int:
    print(f"Backend : {db.describe_backend()}")
    try:
        db.init_db()
        engine = db._resolve_engine(None)
        with engine.begin() as conn:
            conn.execute(text("SELECT 1"))
        n = db.count_companies()
    except Exception as exc:  # noqa: BLE001 - we want to explain any failure
        print("\n[FAILED] Could not connect to the database.")
        print(f"Raw error: {str(exc).splitlines()[0][:200]}")
        print(f"\nWhat to do: {db.explain_connection_error(str(exc))}")
        return 1
    print(f"[OK] Connected. Tables are ready. Companies registered: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
