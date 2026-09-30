"""Reset the WattWise database and create a fresh SIH demo company."""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src import database as db

def main() -> None:
    print("WattWise database RESET")
    print(f"Backend: {db.describe_backend()}")
    answer = input("This permanently deletes all WattWise demo/company history. Type RESET to continue: ").strip()
    if answer != "RESET":
        print("Cancelled. No changes made.")
        return
    db.reset_database()
    record = db.CompanyRecord(
        name="Demo MSME", tier="small", sanctioned_load_kw=100.0,
        industry_type="textile", shift_pattern=[("06:00", "14:00"), ("14:00", "22:00")],
        connection_type="LT",
    )
    company_id, raw_key = db.create_company(record)
    print("\nFresh demo database created.")
    print(f"Company ID : {company_id}")
    print(f"API key    : {raw_key}")
    print("Save this key; it is shown only once.")

if __name__ == "__main__":
    main()
