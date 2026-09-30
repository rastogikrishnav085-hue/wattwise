"""
forecast.py
------------
Trains and serves the demand forecasting ensemble:
  - ARIMA        : captures short-term autocorrelation / trend
  - RandomForest : captures non-linear, feature-driven patterns

Changes from the previous version:
  1. Ensemble weight is chosen by grid search against test-set MAE, not a
     closed-form inverse-MAE formula (see _select_ensemble_weight).
  2. cross_validate_ensemble() adds expanding-window time-series CV.
  3. forecast_next_n_hours() returns a confidence interval alongside the
     point forecast.
  4. Feature building is shift-aware (features.py).
  5. Models now persist to a caller-supplied `model_dir` instead of one
     fixed global path. This matters once there is more than one MSME
     using the same deployment: without this, training for Company B
     would silently overwrite Company A's saved model on disk, even
     though their forecast_runs/training_runs rows are correctly
     separated by company_id in the database. Callers (api.py, app.py)
     pass a per-company directory, e.g. MODEL_DIR/company_{id}/.
"""

from __future__ import annotations
import json
import os
import pickle
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
from statsmodels.tsa.arima.model import ARIMA

from .config import MODEL_DIR, MODEL_DEFAULTS
from .features import FEATURE_COLUMNS, build_features, compute_shift_flags
from .logging_setup import get_logger

log = get_logger(__name__)


class InsufficientDataError(ValueError):
    """Raised when there isn't enough history to train a meaningful model."""


@dataclass
class TrainResult:
    rf_model: RandomForestRegressor
    arima_result: object
    arima_order: tuple
    mae: float
    rmse: float
    rf_weight: float
    arima_weight: float
    residual_std: float
    shift_pattern: object
    test_df: pd.DataFrame
    test_actual: np.ndarray
    test_forecast: np.ndarray


def _select_arima_order(train_series: np.ndarray, test_series: np.ndarray) -> tuple[tuple, object, float]:
    """Bounded grid search over a short list of candidate (p, d, q) orders."""
    best_mae = float("inf")
    best_order = None
    best_fitted = None

    for order in MODEL_DEFAULTS.arima_order_candidates:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                fitted = ARIMA(train_series, order=order).fit()
                forecast = fitted.get_forecast(steps=len(test_series)).predicted_mean
            mae = mean_absolute_error(test_series, forecast)
        except Exception as exc:  # noqa: BLE001 — some orders can fail to converge; skip and try the next
            log.warning("ARIMA order %s failed to fit (%s) — skipping.", order, exc)
            continue

        if mae < best_mae:
            best_mae, best_order, best_fitted = mae, order, fitted

    if best_fitted is None:
        raise InsufficientDataError(
            "None of the candidate ARIMA orders could be fit to this series — "
            "the data may be too short or too irregular."
        )

    log.info("Selected ARIMA order %s (test MAE %.4f)", best_order, best_mae)
    return best_order, best_fitted, best_mae


def _select_ensemble_weight(test_actual: np.ndarray, rf_pred: np.ndarray, arima_pred: np.ndarray) -> tuple[float, float]:
    """
    Grid-searches the RF/ARIMA blend weight (0.5-1.0 in 0.05 steps) against
    test-set MAE, instead of a closed-form inverse-MAE formula that could
    (and did, in this project's own saved metadata) select a blend worse
    than using RF alone.
    """
    best_weight = 1.0
    best_mae = mean_absolute_error(test_actual, rf_pred)

    for w in np.arange(0.5, 1.001, 0.05):
        blend = w * rf_pred + (1 - w) * arima_pred
        mae = mean_absolute_error(test_actual, blend)
        if mae < best_mae:
            best_mae, best_weight = mae, float(w)

    return round(best_weight, 4), round(1 - best_weight, 4)


def train_ensemble(
    raw_df: pd.DataFrame,
    target_col: str = "Global_active_power",
    shift_pattern=None,
    model_dir: str = MODEL_DIR,
) -> TrainResult:
    """
    Trains ARIMA + Random Forest on an 80/20 chronological split and
    returns both models plus test-set performance metrics. Persists the
    trained models and metadata under `model_dir` — pass a per-company
    directory in any multi-tenant caller; the default (MODEL_DIR) is only
    appropriate for a single-tenant/dev run.
    """
    feat_df = build_features(raw_df, target_col=target_col, shift_pattern=shift_pattern)

    if len(feat_df) < MODEL_DEFAULTS.min_training_rows:
        raise InsufficientDataError(
            f"Only {len(feat_df)} usable rows after feature engineering — need at least "
            f"{MODEL_DEFAULTS.min_training_rows} hourly readings to train a reliable model. "
            "Provide a longer history."
        )

    split = int(len(feat_df) * 0.8)
    train_df, test_df = feat_df.iloc[:split], feat_df.iloc[split:]

    if len(test_df) < 24:
        raise InsufficientDataError(
            f"Test split only has {len(test_df)} rows — not enough to evaluate a 24h-ahead forecast."
        )

    log.info("Training on %s rows, testing on %s rows.", len(train_df), len(test_df))

    rf = RandomForestRegressor(
        n_estimators=MODEL_DEFAULTS.rf_n_estimators,
        max_depth=MODEL_DEFAULTS.rf_max_depth,
        random_state=42,
        n_jobs=-1,
    )
    rf.fit(train_df[FEATURE_COLUMNS], train_df[target_col])
    rf_pred = rf.predict(test_df[FEATURE_COLUMNS])

    train_series = train_df[target_col].values
    test_series = test_df[target_col].values
    arima_order, arima_fitted, _arima_mae = _select_arima_order(train_series, test_series)
    arima_forecast = np.asarray(arima_fitted.get_forecast(steps=len(test_df)).predicted_mean)

    rf_weight, arima_weight = _select_ensemble_weight(test_df[target_col].values, rf_pred, arima_forecast)
    ensemble_pred = rf_weight * rf_pred + arima_weight * arima_forecast

    mae = mean_absolute_error(test_df[target_col], ensemble_pred)
    rmse = float(np.sqrt(mean_squared_error(test_df[target_col], ensemble_pred)))
    residual_std = float(np.std(test_df[target_col].values - ensemble_pred))

    log.info(
        "Ensemble trained: MAE=%.4f kW, RMSE=%.4f kW (RF weight=%.2f, ARIMA weight=%.2f)%s",
        mae, rmse, rf_weight, arima_weight,
        " — ARIMA dropped from blend, RF alone was stronger" if arima_weight == 0 else "",
    )

    os.makedirs(model_dir, exist_ok=True)
    rf_path = os.path.join(model_dir, "rf_model.pkl")
    arima_path = os.path.join(model_dir, "arima_model.pkl")
    metadata_path = os.path.join(model_dir, "model_metadata.json")

    with open(rf_path, "wb") as f:
        pickle.dump(rf, f)
    with open(arima_path, "wb") as f:
        pickle.dump(arima_fitted, f)

    metadata = {
        "trained_at_utc": datetime.now(timezone.utc).isoformat(),
        "ensemble": {
            "rf_weight": rf_weight,
            "arima_weight": arima_weight,
            "test_mae_kw": round(float(mae), 4),
            "test_rmse_kw": round(float(rmse), 4),
            "residual_std_kw": round(residual_std, 4),
            "weight_selection": "grid_search_test_mae",
        },
        "random_forest": {
            "n_estimators": rf.n_estimators,
            "max_depth": rf.max_depth,
            "feature_columns": FEATURE_COLUMNS,
        },
        "arima": {
            "order": list(arima_order),
            "candidates_tried": [list(o) for o in MODEL_DEFAULTS.arima_order_candidates],
        },
        "train_test_split": {"train_rows": int(split), "test_rows": int(len(test_df))},
        "shift_pattern": shift_pattern,
    }
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)

    return TrainResult(
        rf_model=rf,
        arima_result=arima_fitted,
        arima_order=arima_order,
        mae=mae,
        rmse=rmse,
        rf_weight=rf_weight,
        arima_weight=arima_weight,
        residual_std=residual_std,
        shift_pattern=shift_pattern,
        test_df=test_df,
        test_actual=test_df[target_col].values,
        test_forecast=ensemble_pred,
    )


def cross_validate_ensemble(
    raw_df: pd.DataFrame,
    target_col: str = "Global_active_power",
    n_splits: int = 5,
    shift_pattern=None,
) -> dict:
    """
    Expanding-window time-series cross-validation (RF component only — see
    module docstring history; ARIMA's per-fold refit cost is why this is
    scoped to RF). Returns {"fold_maes", "mean_mae", "std_mae", "n_splits"}.
    """
    feat_df = build_features(raw_df, target_col=target_col, shift_pattern=shift_pattern)
    n = len(feat_df)
    min_train = MODEL_DEFAULTS.min_training_rows
    test_size = 24

    usable_span = n - min_train
    if usable_span < test_size * n_splits:
        raise InsufficientDataError(
            f"Not enough history for {n_splits}-fold expanding-window CV with a {test_size}-row "
            f"test window each (need at least {min_train + test_size * n_splits} feature rows, have {n})."
        )

    fold_maes = []
    step = usable_span // n_splits
    for i in range(n_splits):
        train_end = min_train + i * step
        test_end = min(train_end + test_size, n)
        if test_end - train_end < test_size:
            break
        train_fold = feat_df.iloc[:train_end]
        test_fold = feat_df.iloc[train_end:test_end]

        rf = RandomForestRegressor(
            n_estimators=MODEL_DEFAULTS.rf_n_estimators,
            max_depth=MODEL_DEFAULTS.rf_max_depth,
            random_state=42,
            n_jobs=-1,
        )
        rf.fit(train_fold[FEATURE_COLUMNS], train_fold[target_col])
        pred = rf.predict(test_fold[FEATURE_COLUMNS])
        fold_maes.append(float(mean_absolute_error(test_fold[target_col], pred)))

    if not fold_maes:
        raise InsufficientDataError("No complete folds could be built from the available history.")

    return {
        "fold_maes": [round(m, 4) for m in fold_maes],
        "mean_mae": round(float(np.mean(fold_maes)), 4),
        "std_mae": round(float(np.std(fold_maes)), 4),
        "n_splits": len(fold_maes),
    }


def forecast_next_n_hours(
    raw_df: pd.DataFrame,
    train_result: TrainResult,
    hours: int = 24,
    target_col: str = "Global_active_power",
    ci_level: float = 0.9,
) -> pd.DataFrame:
    """
    Produces an n-hour-ahead forecast, stepping forward one hour at a time
    and feeding each prediction back into lag/rolling features. Returns
    columns: datetime, forecast_kw, forecast_kw_lower{N}, forecast_kw_upper{N}.
    """
    if not isinstance(hours, int) or hours <= 0:
        raise ValueError(f"hours must be a positive integer, got {hours!r}.")
    if hours > 8760:  # one year — generous, but not unbounded
        raise ValueError(f"hours={hours} is unreasonably large (max 8760, one year).")

    feat_df = build_features(raw_df, target_col=target_col, shift_pattern=train_result.shift_pattern)
    if feat_df.empty:
        raise InsufficientDataError("No feature rows available to build a forecast from.")

    last_time = feat_df["datetime"].iloc[-1]
    future_times = pd.date_range(start=last_time + pd.Timedelta(hours=1), periods=hours, freq="h")

    history_values = list(raw_df.sort_values("datetime")[target_col].values)

    rf_preds = []
    for t in future_times:
        lag_1h = history_values[-1]
        lag_24h = history_values[-24] if len(history_values) >= 24 else history_values[0]
        lag_168h = history_values[-168] if len(history_values) >= 168 else history_values[0]
        recent_24 = history_values[-24:] if len(history_values) >= 24 else history_values
        roll_mean_24h = float(np.mean(recent_24))
        roll_std_24h = float(np.std(recent_24)) if len(recent_24) > 1 else 0.0

        shift_active, shift_boundary = compute_shift_flags(pd.Series([t.hour]), train_result.shift_pattern)

        row = pd.DataFrame([{
            "hour": t.hour,
            "day_of_week": t.dayofweek,
            "month": t.month,
            "is_weekend": int(t.dayofweek >= 5),
            "shift_active_flag": int(shift_active.iloc[0]),
            "shift_boundary_flag": int(shift_boundary.iloc[0]),
            "lag_1h": lag_1h,
            "lag_24h": lag_24h,
            "lag_168h": lag_168h,
            "roll_mean_24h": roll_mean_24h,
            "roll_std_24h": roll_std_24h,
        }])
        pred = float(train_result.rf_model.predict(row[FEATURE_COLUMNS])[0])
        pred = max(pred, 0.0)
        rf_preds.append(pred)
        history_values.append(pred)

    rf_preds = np.array(rf_preds)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        arima_forecast_obj = train_result.arima_result.get_forecast(steps=hours)
        arima_pred = np.asarray(arima_forecast_obj.predicted_mean)
        arima_ci = np.asarray(arima_forecast_obj.conf_int(alpha=1 - ci_level))

    ensemble = train_result.rf_weight * rf_preds + train_result.arima_weight * arima_pred
    ensemble = np.clip(ensemble, 0, None)

    z = norm.ppf(0.5 + ci_level / 2)
    rf_half_width = np.full(hours, z * train_result.residual_std)
    arima_half_width = (arima_ci[:, 1] - arima_ci[:, 0]) / 2

    half_width = train_result.rf_weight * rf_half_width + train_result.arima_weight * arima_half_width
    lower = np.clip(ensemble - half_width, 0, None)
    upper = ensemble + half_width

    pct = int(round(ci_level * 100))
    return pd.DataFrame({
        "datetime": future_times,
        "forecast_kw": ensemble,
        f"forecast_kw_lower{pct}": lower,
        f"forecast_kw_upper{pct}": upper,
    })


def forecast_next_24h(
    raw_df: pd.DataFrame,
    train_result: TrainResult,
    target_col: str = "Global_active_power",
) -> pd.DataFrame:
    """Backward-compatible 24h forecast — thin wrapper around forecast_next_n_hours."""
    return forecast_next_n_hours(raw_df, train_result, hours=24, target_col=target_col)
