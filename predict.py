"""
predict.py
-----------
Standalone inference wrapper — loads already-trained models from a model
directory and produces a forecast without retraining, for quick CLI use,
cron jobs, or wrapping in another script.

Usage:
    python predict.py                          # uses models/ (single-tenant/dev)
    python predict.py --model-dir models/company_3   # a specific company's models

Requires that train_ensemble() has already been run once (via app.py, the
API's /train route, or directly) for whatever model_dir you point at.
"""

from __future__ import annotations
import argparse
import json
import pickle
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from src.config import MODEL_DIR
from src.data_loader import load_consumption_data
from src.forecast import TrainResult, forecast_next_24h
from src.flags import TariffWindow, flag_peak_hours, detect_anomalies
from src.savings import calculate_savings


def load_trained_models(model_dir: str = MODEL_DIR) -> TrainResult:
    rf_path = os.path.join(model_dir, "rf_model.pkl")
    arima_path = os.path.join(model_dir, "arima_model.pkl")
    metadata_path = os.path.join(model_dir, "model_metadata.json")

    if not (os.path.exists(rf_path) and os.path.exists(arima_path)):
        raise FileNotFoundError(
            f"No trained models found in {model_dir}. Run the app once (streamlit run app.py), "
            "call POST /train on the API, or call src.forecast.train_ensemble() directly first."
        )

    with open(rf_path, "rb") as f:
        rf_model = pickle.load(f)
    with open(arima_path, "rb") as f:
        arima_result = pickle.load(f)

    weights = {
        "rf_weight": 0.5, "arima_weight": 0.5, "mae": None, "rmse": None,
        "order": (2, 1, 2), "residual_std": 0.0, "shift_pattern": None,
    }
    if os.path.exists(metadata_path):
        with open(metadata_path) as f:
            meta = json.load(f)
        weights["rf_weight"] = meta["ensemble"]["rf_weight"]
        weights["arima_weight"] = meta["ensemble"]["arima_weight"]
        weights["mae"] = meta["ensemble"]["test_mae_kw"]
        weights["rmse"] = meta["ensemble"]["test_rmse_kw"]
        weights["residual_std"] = meta["ensemble"].get("residual_std_kw", 0.0)
        weights["order"] = tuple(meta["arima"]["order"])
        weights["shift_pattern"] = meta.get("shift_pattern")

    return TrainResult(
        rf_model=rf_model,
        arima_result=arima_result,
        arima_order=weights["order"],
        mae=weights["mae"] or 0.0,
        rmse=weights["rmse"] or 0.0,
        rf_weight=weights["rf_weight"],
        arima_weight=weights["arima_weight"],
        residual_std=weights["residual_std"],
        shift_pattern=weights["shift_pattern"],
        test_df=None,
        test_actual=None,
        test_forecast=None,
    )


def predict(model_dir: str = MODEL_DIR, shift_fraction: float = 0.3) -> dict:
    load_result = load_consumption_data(force_demo=False)
    train_result = load_trained_models(model_dir=model_dir)

    future = forecast_next_24h(load_result.df, train_result)
    tariff = TariffWindow()
    flagged = flag_peak_hours(future, tariff)
    flagged = detect_anomalies(flagged, shift_pattern=train_result.shift_pattern)
    savings = calculate_savings(flagged, tariff, shift_fraction=shift_fraction)

    return {
        "data_source": load_result.source.value,
        "model_dir": model_dir,
        "forecast": future.to_dict(orient="records"),
        "peak_hours_flagged": int(flagged["is_peak_flag"].sum()),
        "anomalies_detected": int(flagged["is_anomaly"].sum()),
        "baseline_cost_24h": round(savings.baseline_cost, 2),
        "optimized_cost_24h": round(savings.optimized_cost, 2),
        "savings_pct": round(savings.savings_pct, 2),
        "estimated_monthly_savings": round(savings.monthly_savings, 2),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WattWise standalone forecast CLI")
    parser.add_argument("--model-dir", default=MODEL_DIR, help="Directory holding rf_model.pkl / arima_model.pkl / model_metadata.json")
    parser.add_argument("--shift-fraction", type=float, default=0.3)
    args = parser.parse_args()

    result = predict(model_dir=args.model_dir, shift_fraction=args.shift_fraction)
    print(json.dumps(result, indent=2, default=str))
