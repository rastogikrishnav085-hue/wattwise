import numpy as np
import pandas as pd
import pytest

from src.data_quality import assess_quality, validate_or_raise, DataQualityError


def _good_df(n=200, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    values = 0.5 + 0.2 * np.sin(np.arange(n) / 24 * 2 * np.pi) + rng.normal(0, 0.02, n)
    return pd.DataFrame({"datetime": idx, "Global_active_power": np.clip(values, 0.01, None)})


def test_good_dataset_passes():
    report = assess_quality(_good_df())
    assert report.passed
    assert report.reasons == []


def test_too_few_rows_fails():
    df = _good_df(n=10)
    report = assess_quality(df)
    assert not report.passed
    assert any("rows" in r for r in report.reasons)


def test_constant_values_fail():
    df = _good_df(n=200)
    df["Global_active_power"] = 1.0
    report = assess_quality(df)
    assert not report.passed
    assert any("constant" in r.lower() for r in report.reasons)


def test_all_missing_values_fail():
    df = _good_df(n=200)
    df["Global_active_power"] = np.nan
    report = assess_quality(df)
    assert not report.passed
    assert any("missing" in r.lower() for r in report.reasons)


def test_high_missing_ratio_fails():
    df = _good_df(n=200)
    df.loc[df.index[:40], "Global_active_power"] = np.nan  # 20% missing
    report = assess_quality(df)
    assert not report.passed
    assert any("missing" in r.lower() for r in report.reasons)


def test_low_missing_ratio_passes_with_warning():
    df = _good_df(n=200)
    df.loc[df.index[:2], "Global_active_power"] = np.nan  # 1% missing
    report = assess_quality(df)
    assert report.passed
    assert any("missing" in w.lower() for w in report.warnings)


def test_negative_values_fail():
    df = _good_df(n=200)
    df.loc[df.index[:5], "Global_active_power"] = -3.0
    report = assess_quality(df)
    assert not report.passed
    assert any("negative" in r.lower() for r in report.reasons)


def test_duplicate_timestamps_fail():
    df = _good_df(n=200)
    df.loc[df.index[1], "datetime"] = df.loc[df.index[0], "datetime"]
    report = assess_quality(df)
    assert not report.passed
    assert any("duplicate" in r.lower() for r in report.reasons)


def test_extreme_outliers_fail():
    df = _good_df(n=200)
    # push >10% of rows to an extreme scale, as if units were wrong (W vs kW)
    df.loc[df.index[:30], "Global_active_power"] = 5000.0
    report = assess_quality(df)
    assert not report.passed
    assert any("outlier" in r.lower() for r in report.reasons)


def test_large_gap_fails():
    idx = list(pd.date_range("2024-01-01", periods=50, freq="h")) + \
          list(pd.date_range("2024-01-10", periods=50, freq="h"))  # ~8 day gap in the middle
    values = np.full(100, 0.5)
    df = pd.DataFrame({"datetime": pd.to_datetime(idx), "Global_active_power": values})
    report = assess_quality(df)
    assert not report.passed
    assert any("gap" in r.lower() for r in report.reasons)


def test_short_history_passes_with_warning():
    df = _good_df(n=100)  # a few days, above MIN_ROWS but well under 2 weeks
    report = assess_quality(df)
    assert report.passed
    assert any("hours" in w.lower() for w in report.warnings)


def test_validate_or_raise_raises_with_all_reasons():
    df = _good_df(n=200)
    df["Global_active_power"] = 1.0  # constant -> guaranteed failure
    with pytest.raises(DataQualityError, match="constant"):
        validate_or_raise(df, label="test dataset")


def test_validate_or_raise_returns_report_on_pass():
    report = validate_or_raise(_good_df(), label="test dataset")
    assert report.passed


def test_shift_pattern_factory_load_is_not_flagged_as_outliers():
    import numpy as np, pandas as pd
    from src.data_quality import assess_quality
    idx = pd.date_range("2024-01-01", periods=24 * 30, freq="h")
    rng = np.random.default_rng(0)
    kw = 15 + 40 * ((idx.hour >= 8) & (idx.hour < 18)) + rng.normal(0, 1, len(idx))
    report = assess_quality(pd.DataFrame({"datetime": idx, "Global_active_power": kw}))
    assert report.passed, report.reasons
