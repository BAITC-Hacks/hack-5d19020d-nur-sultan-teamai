from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

from .config import get_paths, models_config
from .features import build_training_frame
from .storage import ensure_dirs, write_json


MODEL_NAME = "catboost_v1"


def _split_train_valid(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    cfg = models_config().train
    valid_days = int(cfg.get("valid_days", 14))
    cutoff = frame["forecast_origin_utc"].max() - pd.Timedelta(days=valid_days)
    train = frame.loc[frame["forecast_origin_utc"] <= cutoff]
    valid = frame.loc[frame["forecast_origin_utc"] > cutoff]
    if train.empty or valid.empty:
        # tiny fixture fallback: 80/20 by row order after sort
        frame = frame.sort_values("forecast_origin_utc")
        n = max(1, int(len(frame) * 0.8))
        train, valid = frame.iloc[:n], frame.iloc[n:]
        if valid.empty:
            valid = train.tail(max(1, len(train) // 5)).copy()
    return train, valid


def train_model(max_origins: int = 40) -> dict:
    ensure_dirs()
    frame = build_training_frame(max_origins=max_origins)
    feats = models_config().features
    target = models_config().target
    train, valid = _split_train_valid(frame)
    min_rows = int(models_config().train.get("min_train_rows", 50))
    if len(train) < min_rows:
        # still train — MVP on short fixtures
        pass

    params = dict(models_config().catboost)
    model = CatBoostRegressor(**params)
    model.fit(train[feats], train[target], eval_set=(valid[feats], valid[target]))

    pred = model.predict(valid[feats])
    y = valid[target].to_numpy()
    rmse = float(np.sqrt(mean_squared_error(y, pred)))
    mae = float(mean_absolute_error(y, pred))

    paths = get_paths()
    model_dir = paths["models"] / MODEL_NAME
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / "model.cbm"
    model.save_model(str(model_path))

    metrics = {
        "model_version": MODEL_NAME,
        "n_train": int(len(train)),
        "n_valid": int(len(valid)),
        "rmse": rmse,
        "mae": mae,
        "features": feats,
        "model_path": str(model_path),
        "valid_origin_min": str(valid["forecast_origin_utc"].min()),
        "valid_origin_max": str(valid["forecast_origin_utc"].max()),
    }
    write_json(model_dir / "metrics.json", metrics)
    # also keep a small sample of training meta
    write_json(
        model_dir / "train_meta.json",
        {
            "n_rows_total": int(len(frame)),
            "turbines": sorted(frame["turbine_id"].unique().tolist()),
        },
    )
    return metrics


def load_model() -> tuple[CatBoostRegressor, dict]:
    model_dir = get_paths()["models"] / MODEL_NAME
    model_path = model_dir / "model.cbm"
    metrics_path = model_dir / "metrics.json"
    if not model_path.exists():
        train_model()
    model = CatBoostRegressor()
    model.load_model(str(model_path))
    metrics = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else {}
    return model, metrics
