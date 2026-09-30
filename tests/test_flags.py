import pandas as pd
import pytest

from src.flags import TariffWindow, InvalidTariffError, flag_peak_hours, detect_anomalies, detect_rolling_anomalies


def test_tariff_window_rejects_invalid_hour_range():
    with pytest.raises(InvalidTariffError):
        TariffWindow(peak_hours=(22, 18))  # end before start


def test_tariff_window_rejects_non_positive_rate():
    with pytest.raises(InvalidTariffError):
        TariffWindow(peak_rate=0)


def test_tariff_window_rejects_off_peak_more_expensive_than_peak():
    with pytest.raises(InvalidTariffError):
        TariffWindow(peak_rate=4.0, off_peak_rate=12.0)


def test_tariff_window_accepts_valid_config():
    tariff = TariffWindow(peak_rate=12.0, shoulder_rate=7.0, off_peak_rate=4.0)
    assert tariff.rate_for_hour(19) == 12.0
    assert tariff.rate_for_hour(11) == 7.0
    assert tariff.rate_for_hour(2) == 4.0


def test_flag_peak_hours_marks_correct_band():
    tariff = TariffWindow()
    df = pd.DataFrame({
        "datetime": pd.date_range("2024-01-01", periods=24, freq="h"),
        "forecast_kw": [1.0] * 24,
    })
    flagged = flag_peak_hours(df, tariff)
    peak_rows = flagged[flagged["hour"].between(*tariff.peak_hours, inclusive="left")]
    assert peak_rows["is_peak_flag"].all()


def test_flag_peak_hours_requires_datetime_column():
    tariff = TariffWindow()
    with pytest.raises(ValueError):
        flag_peak_hours(pd.DataFrame({"forecast_kw": [1.0]}), tariff)


def test_detect_anomalies_flags_extreme_spike():
    df = pd.DataFrame({
        "datetime": pd.date_range("2024-01-01", periods=10, freq="h"),
        "forecast_kw": [1.0] * 9 + [50.0],  # obvious spike
    })
    result = detect_anomalies(df, z_thresh=2.0)
    assert result["is_anomaly"].iloc[-1]
    assert not result["is_anomaly"].iloc[:-1].any()


def test_detect_rolling_anomalies_on_flat_series_finds_nothing(demo_df):
    flat = demo_df.copy()
    flat["Global_active_power"] = 1.0
    result = detect_rolling_anomalies(flat)
    assert not result["is_anomaly"].any()


# --- Shift-aware anomaly suppression ---

def test_detect_anomalies_suppresses_shift_start_surge():
    """A spike exactly at a configured shift-start hour should NOT be flagged
    when shift_pattern is given — that's expected simultaneous machine start-up,
    not a fault. Without shift_pattern, the same spike is still flagged, showing
    this is genuinely gated on the parameter, not just a lucky threshold."""
    df = pd.DataFrame({
        "datetime": pd.date_range("2024-01-01 00:00", periods=24, freq="h"),
        "forecast_kw": [1.0] * 9 + [50.0] + [1.0] * 14,  # spike at hour 9
    })
    shift_pattern = [("09:00", "17:00")]

    without_shift = detect_anomalies(df, z_thresh=2.0)
    assert without_shift["is_anomaly"].iloc[9]

    with_shift = detect_anomalies(df, z_thresh=2.0, shift_pattern=shift_pattern)
    assert not with_shift["is_anomaly"].iloc[9]


def test_detect_anomalies_still_flags_spikes_outside_shift_boundary():
    df = pd.DataFrame({
        "datetime": pd.date_range("2024-01-01 00:00", periods=24, freq="h"),
        "forecast_kw": [1.0] * 3 + [50.0] + [1.0] * 20,  # spike at hour 3, well outside 9-17 shift
    })
    result = detect_anomalies(df, z_thresh=2.0, shift_pattern=[("09:00", "17:00")])
    assert result["is_anomaly"].iloc[3]


def test_detect_rolling_anomalies_suppresses_shift_boundary(demo_df):
    df = demo_df.copy()
    # inject a clean spike at a shift-start hour somewhere in the middle of the series
    spike_idx = 200
    spike_hour = df.loc[spike_idx, "datetime"].hour
    shift_pattern = [(f"{spike_hour:02d}:00", f"{(spike_hour + 8) % 24:02d}:00")]
    df.loc[spike_idx, "Global_active_power"] = df["Global_active_power"].max() * 20

    without_shift = detect_rolling_anomalies(df)
    with_shift = detect_rolling_anomalies(df, shift_pattern=shift_pattern)

    assert without_shift["is_anomaly"].iloc[spike_idx]
    assert not with_shift["is_anomaly"].iloc[spike_idx]
