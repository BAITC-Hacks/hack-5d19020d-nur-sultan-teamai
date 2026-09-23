from __future__ import annotations

import numpy as np
import pandas as pd

from .config import models_config, time_config
from .ingest import load_hourly
from .weather import fetch_and_cache, snapshot_to_frame


def _cyclic(series: pd.Series, period: float) -> tuple[pd.Series, pd.Series]:
    angle = 2 * np.pi * series / period
    return np.sin(angle), np.cos(angle)


def build_training_frame(max_origins: int = 60) -> pd.DataFrame:
    """Build as-of training rows: weather at lead + observed power for that hour."""
    hourly = load_hourly()
    eligible = hourly.loc[hourly["eligible_target"]].copy()
    if eligible.empty:
        raise ValueError("No eligible hourly targets")

    turbines = sorted(eligible["turbine_id"].unique())
    # Origins: daily midnight UTC within observed range (leave horizon room)
    start = eligible["valid_start_utc"].min().floor("D") + pd.Timedelta(days=7)
    end = eligible["valid_start_utc"].max().floor("D") - pd.Timedelta(hours=time_config().horizon_hours)
    if end <= start:
        # Short fixture: sample origins every 12h
        origins = pd.date_range(eligible["valid_start_utc"].min(), eligible["valid_start_utc"].max(), freq="12h", tz="UTC")
        origins = origins[:-2] if len(origins) > 3 else origins[:1]
    else:
        origins = pd.date_range(start, end, freq="D", tz="UTC")
    if len(origins) > max_origins:
        origins = origins[-max_origins:]

    rows = []
    for origin in origins:
        snap = fetch_and_cache(origin.to_pydatetime())
        weather = snapshot_to_frame(snap)
        for turbine in turbines:
            w = weather.loc[weather["turbine_id"] == turbine].copy()
            w["lead_hours"] = ((w["valid_start_utc"] - origin) / pd.Timedelta(hours=1)).astype(int) + 1
            obs = eligible.loc[eligible["turbine_id"] == turbine, ["valid_start_utc", "power_normalized"]]
            merged = w.merge(obs, on="valid_start_utc", how="inner")
            if merged.empty:
                continue
            hour = merged["valid_start_utc"].dt.hour
            doy = merged["valid_start_utc"].dt.dayofyear
            hs, hc = _cyclic(hour, 24)
            ds, dc = _cyclic(doy, 365.25)
            merged["hour_sin"] = hs
            merged["hour_cos"] = hc
            merged["doy_sin"] = ds
            merged["doy_cos"] = dc
            merged["forecast_origin_utc"] = origin
            merged["weather_snapshot_id"] = snap.snapshot_id
            rows.append(merged)

    if not rows:
        raise ValueError("Could not build any training rows")
    frame = pd.concat(rows, ignore_index=True)
    feats = models_config().features
    missing = [f for f in feats if f not in frame.columns]
    if missing:
        raise ValueError(f"Missing features: {missing}")
    return frame


def build_inference_frame(origin: pd.Timestamp, snap_frame: pd.DataFrame, snapshot_id: str) -> pd.DataFrame:
    origin = pd.Timestamp(origin)
    if origin.tzinfo is None:
        origin = origin.tz_localize("UTC")
    else:
        origin = origin.tz_convert("UTC")
    frame = snap_frame.copy()
    frame["lead_hours"] = ((frame["valid_start_utc"] - origin) / pd.Timedelta(hours=1)).astype(int) + 1
    hour = frame["valid_start_utc"].dt.hour
    doy = frame["valid_start_utc"].dt.dayofyear
    frame["hour_sin"], frame["hour_cos"] = _cyclic(hour, 24)
    frame["doy_sin"], frame["doy_cos"] = _cyclic(doy, 365.25)
    frame["forecast_origin_utc"] = origin
    frame["weather_snapshot_id"] = snapshot_id
    return frame
