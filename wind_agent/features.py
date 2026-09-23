import numpy as np
import pandas as pd

FEATURES = ["wind100", "u100", "v100", "temperature_2m", "wind_squared", "direction_sin",
            "direction_cos", "hour_sin", "hour_cos", "year_sin", "year_cos", "nwp_lead_hours"]


def features(frame):
    out = frame[["wind100", "u100", "v100", "temperature_2m", "nwp_lead_hours"]].copy()
    t = pd.to_datetime(frame.target_time, utc=True)
    speed = frame.wind100.to_numpy()
    out["wind_squared"] = speed**2
    out["direction_sin"] = frame.v100 / np.maximum(speed, .1)
    out["direction_cos"] = frame.u100 / np.maximum(speed, .1)
    out["hour_sin"] = np.sin(2 * np.pi * t.dt.hour / 24)
    out["hour_cos"] = np.cos(2 * np.pi * t.dt.hour / 24)
    out["year_sin"] = np.sin(2 * np.pi * t.dt.dayofyear / 365.25)
    out["year_cos"] = np.cos(2 * np.pi * t.dt.dayofyear / 365.25)
    out = out[FEATURES].astype(float)
    if not np.isfinite(out.to_numpy()).all():
        raise ValueError("Non-finite weather features")
    return out


def training_table(weather, observed, cutoff):
    from .config import utc
    cutoff = utc(cutoff)
    valid = observed.loc[observed.eligible & (observed.obs_available_at <= cutoff)]
    merged = weather.merge(valid[["site_id", "target_time", "power", "obs_available_at"]],
                           on=["site_id", "target_time"], validate="many_to_one")
    merged = merged[(merged.origin < cutoff) & (merged.target_time < cutoff)]
    if (merged.weather_available_at > merged.origin).any():
        raise ValueError("Weather availability leakage")
    if not merged.empty:
        if merged.config_hash.nunique() != 1:
            raise ValueError("Mixed feature contracts")
        counts = merged.groupby(["site_id", "target_time"]).power.transform("size")
        merged = merged.assign(sample_weight=1/counts)
    return merged.sort_values(["target_time", "site_id", "origin"]).reset_index(drop=True)
