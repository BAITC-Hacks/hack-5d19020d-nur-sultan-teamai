from __future__ import annotations

from datetime import datetime

import pandas as pd

from .config import get_paths, models_config, sites_config, time_config
from .features import build_inference_frame
from .ingest import load_hourly
from .schemas import ForecastBundle, ForecastRow
from .storage import ensure_dirs, write_frame, write_json
from .train import MODEL_NAME, load_model
from .weather import fetch_and_cache, snapshot_to_frame


def _parse_origin(origin: datetime | str | None) -> pd.Timestamp:
    if origin is None:
        # default: day after last observation day at 00:00 UTC
        hourly = load_hourly()
        last = hourly["valid_start_utc"].max().floor("D")
        return last  # often 2026-01-31 for real data; for fixtures similar
    ts = pd.Timestamp(origin)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def run_forecast(origin: datetime | str | None = None, turbine_ids: list[str] | None = None) -> ForecastBundle:
    ensure_dirs()
    origin_ts = _parse_origin(origin)
    sites = sites_config().sites
    if turbine_ids:
        sites = [s for s in sites if s.turbine_id in turbine_ids]
    snap = fetch_and_cache(origin_ts.to_pydatetime())
    weather = snapshot_to_frame(snap)
    weather = weather.loc[weather["turbine_id"].isin([s.turbine_id for s in sites])]
    frame = build_inference_frame(origin_ts, weather, snap.snapshot_id)
    model, metrics = load_model()
    feats = models_config().features
    preds = model.predict(frame[feats])
    frame = frame.copy()
    frame["power_point_normalized"] = preds.clip(0, 1)

    rows: list[ForecastRow] = []
    for _, r in frame.iterrows():
        rows.append(
            ForecastRow(
                turbine_id=r["turbine_id"],
                forecast_origin_utc=origin_ts.to_pydatetime(),
                valid_start_utc=pd.Timestamp(r["valid_start_utc"]).to_pydatetime(),
                valid_end_utc=(pd.Timestamp(r["valid_start_utc"]) + pd.Timedelta(hours=1)).to_pydatetime(),
                lead_hours=int(r["lead_hours"]),
                power_point_normalized=float(r["power_point_normalized"]),
                model_version=metrics.get("model_version", MODEL_NAME),
                weather_snapshot_id=snap.snapshot_id,
                contract_status=snap.contract_status,
            )
        )

    # Score only if actuals exist for the horizon window
    hourly = load_hourly()
    actual = hourly.loc[
        (hourly["eligible_target"])
        & (hourly["valid_start_utc"] >= origin_ts)
        & (hourly["valid_start_utc"] < origin_ts + pd.Timedelta(hours=time_config().horizon_hours))
    ]
    score_status = "not_evaluated"
    score_metrics: dict = {}
    notes = list(snap.notes)
    if actual.empty:
        notes.append("No eligible actuals in forecast window → score_status=not_evaluated")
    else:
        merged = frame.merge(
            actual[["turbine_id", "valid_start_utc", "power_normalized"]],
            on=["turbine_id", "valid_start_utc"],
            how="inner",
        )
        if merged.empty:
            notes.append("Weather/actual join empty → not_evaluated")
        else:
            err = merged["power_point_normalized"] - merged["power_normalized"]
            score_status = "ok"
            score_metrics = {
                "n": int(len(merged)),
                "mae": float(err.abs().mean()),
                "rmse": float((err**2).mean() ** 0.5),
            }

    bundle = ForecastBundle(
        origin_utc=origin_ts.to_pydatetime(),
        model_version=metrics.get("model_version", MODEL_NAME),
        contract_status=snap.contract_status,
        rows=rows,
        score_status=score_status,
        metrics=score_metrics,
        notes=notes,
    )

    export_dir = get_paths()["exports"]
    stamp = origin_ts.strftime("%Y%m%dT%H%M")
    out_csv = export_dir / f"forecast_{stamp}.csv"
    out_json = export_dir / f"forecast_{stamp}.json"
    write_frame(out_csv, pd.DataFrame([r.model_dump() for r in rows]))
    write_json(out_json, bundle.model_dump())
    return bundle


def export_submission(origin: datetime | str | None = None) -> dict:
    """Simplified long-table export for demo / jury packaging."""
    bundle = run_forecast(origin=origin)
    path = get_paths()["exports"] / "submission_preview.csv"
    df = pd.DataFrame([r.model_dump() for r in bundle.rows])
    write_frame(path, df)
    return {
        "path": str(path),
        "n_rows": len(df),
        "score_status": bundle.score_status,
        "contract_status": bundle.contract_status,
        "origin_utc": str(bundle.origin_utc),
    }
