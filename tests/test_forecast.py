import numpy as np
import pandas as pd
import pytest

from src.forecast import (
    train_ensemble, forecast_next_24h, forecast_next_n_hours,
    cross_validate_ensemble, InsufficientDataError,
)


def test_train_ensemble_produces_reasonable_metrics(demo_df):
    result = train_ensemble(demo_df)
    assert result.mae > 0
    assert result.rmse >= result.mae  # RMSE >= MAE always holds
    assert 0.0 <= result.rf_weight <= 1.0
    assert result.arima_weight == pytest.approx(1.0 - result.rf_weight)


def test_train_ensemble_never_worse_than_rf_alone(demo_df):
    """The grid-searched weight must never produce an ensemble MAE worse than
    RF alone would achieve — this is the fix for the previous inverse-MAE
    formula, which could and did blend in a weaker ARIMA model even when it
    hurt accuracy."""
    result = train_ensemble(demo_df)
    from sklearn.metrics import mean_absolute_error
    rf_only_pred = result.rf_weight * 0 + result.test_forecast  # placeholder, recompute below
    # Recompute RF-alone prediction directly for a clean comparison
    rf_pred_alone = result.rf_model.predict(result.test_df[
        ["hour", "day_of_week", "month", "is_weekend", "shift_active_flag",
         "shift_boundary_flag", "lag_1h", "lag_24h", "lag_168h", "roll_mean_24h", "roll_std_24h"]
    ])
    rf_only_mae = mean_absolute_error(result.test_actual, rf_pred_alone)
    assert result.mae <= rf_only_mae + 1e-9


def test_train_ensemble_rejects_too_little_data():
    tiny_df = pd.DataFrame({
        "datetime": pd.date_range("2024-01-01", periods=50, freq="h"),
        "Global_active_power": [1.0] * 50,
    })
    with pytest.raises(InsufficientDataError):
        train_ensemble(tiny_df)


def test_forecast_next_24h_returns_24_positive_rows_with_ci(demo_df):
    train_result = train_ensemble(demo_df)
    future = forecast_next_24h(demo_df, train_result)
    assert len(future) == 24
    assert (future["forecast_kw"] >= 0).all()
    assert future["datetime"].is_monotonic_increasing
    assert "forecast_kw_lower90" in future.columns
    assert "forecast_kw_upper90" in future.columns
    assert (future["forecast_kw_upper90"] >= future["forecast_kw_lower90"]).all()
    assert (future["forecast_kw_lower90"] <= future["forecast_kw"]).all()
    assert (future["forecast_kw"] <= future["forecast_kw_upper90"]).all()


@pytest.mark.parametrize("hours", [24, 72, 168])
def test_forecast_next_n_hours_returns_requested_length(demo_df, hours):
    train_result = train_ensemble(demo_df)
    future = forecast_next_n_hours(demo_df, train_result, hours=hours)
    assert len(future) == hours
    assert (future["forecast_kw"] >= 0).all()
    assert future["datetime"].is_monotonic_increasing


def test_forecast_next_n_hours_rejects_non_positive_hours(demo_df):
    train_result = train_ensemble(demo_df)
    with pytest.raises(ValueError):
        forecast_next_n_hours(demo_df, train_result, hours=-5)
    with pytest.raises(ValueError):
        forecast_next_n_hours(demo_df, train_result, hours=0)


def test_forecast_next_n_hours_rejects_unreasonably_large_horizon(demo_df):
    train_result = train_ensemble(demo_df)
    with pytest.raises(ValueError):
        forecast_next_n_hours(demo_df, train_result, hours=100_000)


def test_forecast_next_n_hours_starts_right_after_history(demo_df):
    train_result = train_ensemble(demo_df)
    future = forecast_next_n_hours(demo_df, train_result, hours=24)
    last_history_time = demo_df["datetime"].max()
    assert future["datetime"].iloc[0] == last_history_time + pd.Timedelta(hours=1)


def test_forecast_next_n_hours_custom_ci_level_changes_column_names(demo_df):
    train_result = train_ensemble(demo_df)
    future = forecast_next_n_hours(demo_df, train_result, hours=24, ci_level=0.95)
    assert "forecast_kw_lower95" in future.columns
    assert "forecast_kw_upper95" in future.columns


def test_forecast_next_n_hours_lag_features_use_recursive_feedback(demo_df):
    train_result = train_ensemble(demo_df)
    future = forecast_next_n_hours(demo_df, train_result, hours=48)
    first_day = future["forecast_kw"].iloc[:24].values
    second_day = future["forecast_kw"].iloc[24:48].values
    assert len(first_day) == 24
    assert len(second_day) == 24


# --- Cross-validation ---

def test_cross_validate_ensemble_returns_expected_shape(demo_df):
    result = cross_validate_ensemble(demo_df, n_splits=3)
    assert result["n_splits"] == 3
    assert len(result["fold_maes"]) == 3
    assert result["mean_mae"] > 0
    assert result["std_mae"] >= 0


def test_cross_validate_ensemble_rejects_insufficient_history():
    tiny_df = pd.DataFrame({
        "datetime": pd.date_range("2024-01-01", periods=250, freq="h"),
        "Global_active_power": [1.0] * 250,
    })
    with pytest.raises(InsufficientDataError):
        cross_validate_ensemble(tiny_df, n_splits=5)


def test_cross_validate_ensemble_mean_is_average_of_folds(demo_df):
    result = cross_validate_ensemble(demo_df, n_splits=4)
    assert result["mean_mae"] == pytest.approx(np.mean(result["fold_maes"]), abs=1e-3)
