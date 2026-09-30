"""Run the bundled dataset validation suite through WattWise's upload path."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.data_loader import load_from_upload, DataLoadError

DATA = ROOT / "demo_data"
EXPECTED_REJECT = {"07_negative_value_quality_test.csv", "08_constant_value_quality_test.csv"}
FILES = sorted(DATA.glob("*.csv"))
failures = 0
for path in FILES:
    rejected = False
    try:
        result = load_from_upload(path.read_bytes(), path.name)
        print(f"[OK] {path.name}: {len(result.df):,} hourly rows")
    except DataLoadError as exc:
        rejected = True
        if path.name in EXPECTED_REJECT:
            print(f"[OK] {path.name}: correctly rejected by quality gate")
        else:
            failures += 1
            print(f"[FAIL] {path.name}: {exc}")
    if path.name in EXPECTED_REJECT and not rejected:
        failures += 1
        print(f"[FAIL] {path.name}: expected the quality gate to reject it")

print(f"Checked {len(FILES)} bundled datasets.")
if failures:
    raise SystemExit(f"Dataset suite failed with {failures} unexpected result(s).")
print("Dataset suite passed.")
