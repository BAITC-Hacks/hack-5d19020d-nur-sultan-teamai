import uuid

import numpy as np
import pandas as pd

from .config import data_root, digest, iso, now, project, utc
from .models import active_model
from .storage import atomic_bytes, read_json, sha256, write_frame, write_json
from .weather import fetch_weather


def assert_forecast(frame, origin, cfg):
    expected = len(cfg.sites) * cfg.forecast_hours
    if len(frame) != expected or frame.duplicated(["site_id", "target_time"]).any():
        raise ValueError("Missing/duplicate forecast rows")
    target = pd.date_range(utc(origin), periods=cfg.forecast_hours, freq="h")
    if set(frame.site_id) != {s.site_id for s in cfg.sites}:
        raise ValueError("Unexpected forecast sites")
    for _, group in frame.groupby("site_id"):
        if list(group.target_time) != list(target):
            raise ValueError("Incorrect forecast horizon")
    if not np.isfinite(frame.prediction).all() or not frame.prediction.between(0, 1).all():
        raise ValueError("Invalid normalized prediction")
    if (frame.weather_available_at > frame.origin).any():
        raise ValueError("Future weather leakage")
    if (pd.to_datetime(frame.fit_cutoff, utc=True) > frame.origin).any():
        raise ValueError("Model trained after forecast origin")
    quantiles = frame[["p10", "p50", "p90"]]
    if quantiles.notna().any().any():
        if not np.isfinite(quantiles.to_numpy()).all():
            raise ValueError("Incomplete interval predictions")
        if (frame.p10 > frame.p50).any() or (frame.p50 > frame.p90).any():
            raise ValueError("Crossed quantiles")


def predict_origin(origin, model=None, strict=False):
    cfg, origin = project(), utc(origin)
    if strict and not (cfg.time_metadata_confirmed and cfg.weather_release_lag_confirmed):
        raise ValueError("Strict export blocked: time metadata and publication policy are unconfirmed")
    model = model or active_model()
    if utc(model.card["fit_cutoff"]) > origin:
        raise ValueError("Model trained after forecast origin")
    weather, source = fetch_weather(origin)
    identity = digest({"origin": iso(origin), "model": model.card["version"],
                       "weather": source["sha256"], "config": cfg.fingerprint, "strict": strict})
    index = data_root() / "forecasts" / "by_key" / f"{identity}.json"
    if index.exists():
        ref = read_json(index)
        directory = data_root() / "forecasts" / ref["forecast_id"]
        manifest = read_json(directory / "manifest.json")
        if sha256(directory / "forecast.parquet") != manifest["parquet_sha256"]:
            raise ValueError("Forecast artifact checksum mismatch")
        return pd.read_parquet(directory / "forecast.parquet"), manifest
    prediction = model.predict(weather)
    frame = pd.concat([weather.reset_index(drop=True), prediction.reset_index(drop=True)], axis=1)
    frame["model_version"] = model.card["version"]
    frame["fit_cutoff"] = model.card["fit_cutoff"]
    frame["computed_at"] = now()
    frame["mode"] = "weather_only_frozen"
    frame["provisional"] = not (cfg.time_metadata_confirmed and cfg.weather_release_lag_confirmed)
    for column in frame.columns:
        if isinstance(frame[column].dtype, pd.DatetimeTZDtype):
            frame[column] = frame[column].astype("datetime64[ns, UTC]")
    assert_forecast(frame, origin, cfg)
    forecast_id = f"{origin:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:10]}"
    directory = data_root() / "forecasts" / forecast_id
    write_frame(directory / "forecast.parquet", frame)
    atomic_bytes(directory / "forecast.csv", frame.to_csv(index=False).encode("utf-8-sig"))
    manifest = {"forecast_id": forecast_id, "identity": identity, "origin": iso(origin), "rows": len(frame),
                "computed_at": iso(now()), "model_version": model.card["version"], "model_kind": model.kind,
                "fit_cutoff": model.card["fit_cutoff"], "config_hash": cfg.fingerprint,
                "weather_run": source["run_init"], "weather_available_at": source["available_at"],
                "weather_sha256": source["sha256"], "grid": source["grid"],
                "parquet_sha256": sha256(directory / "forecast.parquet"),
                "csv_sha256": sha256(directory / "forecast.csv"),
                "provisional": bool(frame.provisional.any()), "strict": strict,
                "unit": "normalized_active_line_side_power", "target_interval": "[target_time, target_time+1h)",
                "quantile_note": "Marginal 10/50/90% quantiles; empirical coverage in January holdout. Not energy bounds.",
                "checks": {"rows": True, "finite": True, "causal_weather": True, "model_cutoff": True}}
    write_json(directory / "manifest.json", manifest)
    write_json(index, {"forecast_id": forecast_id})
    return frame, manifest


def replay(start="2026-01-31T00:00Z", end="2026-02-28T00:00Z", strict=False, progress=None, model_version=None):
    start, end = utc(start), utc(end)
    if start > end or (end-start).days > 366:
        raise ValueError("Replay must span between 0 and 366 days")
    from .models import PowerModel
    model = PowerModel.load(model_version) if model_version else active_model()
    frames, manifests = [], []
    for origin in pd.date_range(start, end, freq="D"):
        frame, manifest = predict_origin(origin, model=model, strict=strict)
        frames.append(frame)
        manifests.append(manifest)
        if progress:
            progress(iso(origin), manifest["forecast_id"])
    all_rows = pd.concat(frames, ignore_index=True)
    run_id = f"replay-{now():%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    directory = data_root() / "replays" / run_id
    write_frame(directory / "all_forecasts.parquet", all_rows)
    atomic_bytes(directory / "all_forecasts.csv", all_rows.to_csv(index=False).encode("utf-8-sig"))
    feb = all_rows[(all_rows.target_time >= utc("2026-02-01T00:00Z")) &
                   (all_rows.target_time < utc("2026-03-01T00:00Z"))]
    atomic_bytes(directory / "february_origins.csv", feb.to_csv(index=False).encode("utf-8-sig"))
    # Explicit optional reduction: newest origin available before each target hour.
    single = feb.sort_values("origin").drop_duplicates(["site_id", "target_time"], keep="last")
    atomic_bytes(directory / "february_latest_origin.csv", single.to_csv(index=False).encode("utf-8-sig"))
    manifest = {"id": run_id, "origins": len(frames), "rows": len(all_rows), "february_rows": len(feb),
                "february_unique_site_hours": len(single), "start": iso(start), "end": iso(end),
                "model_version": model.card["version"], "model_frozen_entire_replay": True,
                "forecast_ids": [m["forecast_id"] for m in manifests],
                "strict": strict, "provisional": any(m["provisional"] for m in manifests),
                "february_actuals_available": False, "february_metrics": None,
                "files": {p.name: sha256(p) for p in directory.iterdir() if p.is_file()}}
    write_json(directory / "manifest.json", manifest)
    write_json(data_root() / "replays" / "latest.json", manifest)
    return manifest


def list_forecasts(limit=100):
    roots = sorted((data_root() / "forecasts").glob("*/manifest.json"), reverse=True)[:limit]
    return [read_json(p) for p in roots]
