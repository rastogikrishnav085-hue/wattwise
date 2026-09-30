import pandas as pd
import pytest

from src.data_loader import (
    load_consumption_data, load_from_upload, _load_real_uci, _parse_uci_format,
    DataSource, DataLoadError, MAX_UPLOAD_SIZE_MB,
)


def _make_uci_content(n_hours: int = 200, start="2024-01-01") -> str:
    base = pd.Timestamp(start)
    lines = ["Date;Time;Global_active_power;Global_reactive_power;Voltage;Global_intensity"]
    for i in range(n_hours):
        t = base + pd.Timedelta(hours=i)
        lines.append(f"{t.strftime('%d/%m/%Y')};{t.strftime('%H:%M:%S')};{0.5 + 0.1*(i % 5)};0.1;230.0;2.0")
    return "\n".join(lines)


def test_demo_data_has_expected_columns(demo_df):
    assert set(demo_df.columns) == {"datetime", "Global_active_power"}


def test_demo_data_is_hourly_and_sorted(demo_df):
    assert demo_df["datetime"].is_monotonic_increasing
    diffs = demo_df["datetime"].diff().dropna().unique()
    assert len(diffs) == 1
    assert diffs[0] == pd.Timedelta(hours=1)


def test_demo_data_has_no_negative_consumption(demo_df):
    assert (demo_df["Global_active_power"] >= 0).all()


def test_force_demo_flag_reports_synthetic_source():
    result = load_consumption_data(force_demo=True)
    assert result.source == DataSource.DEMO_SYNTHETIC


def test_rejects_unknown_scenario():
    with pytest.raises(ValueError):
        load_consumption_data(force_demo=True, scenario="not_a_real_scenario")


def test_high_demand_scenario_has_higher_mean_than_normal():
    normal = load_consumption_data(force_demo=True, scenario="normal").df
    high = load_consumption_data(force_demo=True, scenario="high_demand").df
    assert high["Global_active_power"].mean() > normal["Global_active_power"].mean()


def test_anomaly_heavy_scenario_has_more_extreme_spikes_than_normal():
    normal = load_consumption_data(force_demo=True, scenario="normal").df
    heavy = load_consumption_data(force_demo=True, scenario="anomaly_heavy").df
    normal_p99 = normal["Global_active_power"].quantile(0.99)
    heavy_p99 = heavy["Global_active_power"].quantile(0.99)
    assert heavy_p99 > normal_p99


# --- MSME shift-shaped scenario ---

def test_msme_shift_scenario_loads():
    result = load_consumption_data(force_demo=True, scenario="msme_shift")
    assert result.source == DataSource.DEMO_SYNTHETIC
    assert set(result.df.columns) == {"datetime", "Global_active_power"}


def test_msme_shift_scenario_has_lower_weekend_consumption():
    """Opposite of the household scenarios: a factory floor should use LESS
    power on weekends, not more."""
    df = load_consumption_data(force_demo=True, scenario="msme_shift").df
    df = df.copy()
    df["is_weekend"] = df["datetime"].dt.dayofweek.isin([5, 6])
    weekday_mean = df.loc[~df["is_weekend"], "Global_active_power"].mean()
    weekend_mean = df.loc[df["is_weekend"], "Global_active_power"].mean()
    assert weekend_mean < weekday_mean


def test_msme_shift_scenario_respects_custom_shift_pattern():
    """A night-shift pattern should push high consumption into night hours,
    not the default 9-17 window."""
    df = load_consumption_data(
        force_demo=True, scenario="msme_shift", shift_pattern=[("22:00", "06:00")]
    ).df
    df = df.copy()
    df["hour"] = df["datetime"].dt.hour
    night_hours = df["hour"].apply(lambda h: h >= 22 or h < 6)
    day_hours = ~night_hours
    assert df.loc[night_hours, "Global_active_power"].mean() > df.loc[day_hours, "Global_active_power"].mean()


def test_msme_shift_scenario_has_elevated_variance_at_shift_boundaries():
    """Shift-start surges should make consumption noticeably more variable
    right at the boundary hours than in the middle of a shift."""
    df = load_consumption_data(force_demo=True, scenario="msme_shift").df.copy()
    df["hour"] = df["datetime"].dt.hour
    boundary_std = df.loc[df["hour"].isin([9, 10]), "Global_active_power"].std()
    mid_shift_std = df.loc[df["hour"].isin([12, 13]), "Global_active_power"].std()
    assert boundary_std > mid_shift_std


# --- Regression tests for the real UCI-format file / upload parsing path ---

def test_load_real_uci_parses_date_and_time_correctly(tmp_path):
    content = _make_uci_content(n_hours=100)
    file_path = tmp_path / "household_power_consumption.txt"
    file_path.write_text(content)

    df, quality = _load_real_uci(str(file_path))
    assert set(df.columns) == {"datetime", "Global_active_power"}
    assert df["datetime"].is_monotonic_increasing
    assert df["datetime"].iloc[0] == pd.Timestamp("2024-01-01 00:00:00")
    assert len(df) >= 48
    assert quality.passed


def test_load_real_uci_rejects_missing_date_time_columns(tmp_path):
    file_path = tmp_path / "bad.txt"
    file_path.write_text("Foo;Bar\n1;2\n3;4")
    with pytest.raises(DataLoadError):
        _load_real_uci(str(file_path))


def test_load_from_upload_parses_correctly():
    content = _make_uci_content(n_hours=100)
    result = load_from_upload(content.encode("utf-8"), "my_data.csv")
    assert result.source == DataSource.UPLOADED
    assert result.df["datetime"].is_monotonic_increasing
    assert len(result.df) >= 48


def test_load_from_upload_rejects_bad_extension():
    with pytest.raises(DataLoadError, match="Unsupported file type"):
        load_from_upload(b"whatever content", "malware.exe")


def test_load_from_upload_rejects_empty_file():
    with pytest.raises(DataLoadError, match="empty"):
        load_from_upload(b"", "empty.csv")


def test_load_from_upload_rejects_oversized_file():
    oversized = b"x" * ((MAX_UPLOAD_SIZE_MB + 1) * 1024 * 1024)
    with pytest.raises(DataLoadError, match="exceeds"):
        load_from_upload(oversized, "huge.csv")


def test_load_from_upload_rejects_too_short_history():
    content = _make_uci_content(n_hours=10)
    with pytest.raises(DataLoadError, match="too little"):
        load_from_upload(content.encode("utf-8"), "tiny.csv")


def test_load_from_upload_never_writes_to_disk(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    content = _make_uci_content(n_hours=100)
    load_from_upload(content.encode("utf-8"), "../../etc/passwd.csv")
    assert list(tmp_path.iterdir()) == []


# --- Data quality integration: a file that PARSES fine but is garbage gets rejected ---

def test_upload_rejects_constant_value_file():
    base = pd.Timestamp("2024-01-01")
    lines = ["Date;Time;Global_active_power;Global_reactive_power;Voltage;Global_intensity"]
    for i in range(100):
        t = base + pd.Timedelta(hours=i)
        lines.append(f"{t.strftime('%d/%m/%Y')};{t.strftime('%H:%M:%S')};1.0;0.1;230.0;2.0")
    content = "\n".join(lines)
    with pytest.raises(DataLoadError, match="constant"):
        load_from_upload(content.encode("utf-8"), "constant.csv")


def test_upload_rejects_all_negative_file():
    base = pd.Timestamp("2024-01-01")
    lines = ["Date;Time;Global_active_power;Global_reactive_power;Voltage;Global_intensity"]
    for i in range(100):
        t = base + pd.Timedelta(hours=i)
        lines.append(f"{t.strftime('%d/%m/%Y')};{t.strftime('%H:%M:%S')};{-1.0 - (i % 3)};0.1;230.0;2.0")
    content = "\n".join(lines)
    with pytest.raises(DataLoadError, match="negative"):
        load_from_upload(content.encode("utf-8"), "negative.csv")


def test_upload_accepts_realistic_varied_file():
    content = _make_uci_content(n_hours=200)
    result = load_from_upload(content.encode("utf-8"), "good.csv")
    assert result.quality is not None
    assert result.quality.passed


def test_demo_data_scales_to_sanctioned_load_and_anchors_to_today():
    import pandas as pd
    df = load_consumption_data(force_demo=True, scenario="high_demand", sanctioned_load_kw=200, anchor_to_today=True).df
    assert df["Global_active_power"].quantile(0.97) > 200          # stress scenario exceeds the limit
    ok = load_consumption_data(force_demo=True, scenario="msme_shift", sanctioned_load_kw=200).df
    assert 150 < ok["Global_active_power"].quantile(0.97) < 250    # near-limit MSME shape
    assert df["datetime"].max() > pd.Timestamp.now() - pd.Timedelta(hours=3)


def test_default_demo_data_is_unchanged_without_new_arguments():
    df = load_consumption_data(force_demo=True).df
    assert df["Global_active_power"].max() < 10


def test_upload_accepts_common_msmE_datetime_and_load_columns():
    rows = []
    start = pd.Timestamp("2024-01-01")
    for i in range(100):
        t = start + pd.Timedelta(hours=i)
        rows.append(f"{t.strftime('%Y-%m-%d %H:%M:%S')},{50 + (i % 5)}")
    content = "timestamp,load_kw\n" + "\n".join(rows)
    result = load_from_upload(content.encode("utf-8"), "msme_export.csv")
    assert result.source == DataSource.UPLOADED
    assert set(result.df.columns) == {"datetime", "Global_active_power"}
    assert len(result.df) >= 48
