"""Monthly blackout validation, separate January holdout, explicit coverage denominators."""
import uuid

import numpy as np
import pandas as pd

from .config import data_root, iso, now, project, utc
from .features import training_table
from .ingest import observations
from .models import CANDIDATES, PowerModel
from .storage import read_json, write_frame, write_json
from .weather import cached_weather


def metrics(frame, expected=None):
    valid = frame.power.notna() & frame.prediction.notna()
    f = frame.loc[valid]
    result = {"expected_rows": int(expected if expected is not None else len(frame)),
              "scored_rows": int(len(f)), "coverage": len(f)/(expected if expected else max(1, len(frame)))}
    if f.empty:
        return {**result, "rmse": None, "mae": None, "bias": None}
    err = f.prediction - f.power
    result.update(rmse=float(np.sqrt(np.mean(err**2))), mae=float(np.mean(abs(err))), bias=float(np.mean(err)))
    if {"p10", "p50", "p90"}.issubset(f.columns) and f[["p10", "p50", "p90"]].notna().all().all():
        result["interval_coverage_80"] = float(((f.power >= f.p10) & (f.power <= f.p90)).mean())
        result["interval_width"] = float((f.p90-f.p10).mean())
        for q, col in [(.1, "p10"), (.5, "p50"), (.9, "p90")]:
            error = f.power - f[col]
            result[f"pinball_{col}"] = float(np.maximum(q*error, (q-1)*error).mean())
    return result


def monthly_origins(profile="mvp"):
    """MVP samples four origin days per month. Full uses every daily origin."""
    if profile not in ("mvp", "full"):
        raise ValueError("Profile must be mvp or full")
    if profile == "full":
        return list(pd.date_range("2023-03-11", "2026-02-28", freq="D", tz="UTC"))
    # 2024 history spans all seasons; validation includes all 12 months of 2025.
    history = list(pd.date_range("2024-01-01", "2024-12-31", freq="14D", tz="UTC"))
    development = [pd.Timestamp(year=2025, month=m, day=d, tz="UTC") for m in range(1, 13) for d in (1, 8, 15, 22)]
    holdout = list(pd.date_range("2026-01-01", "2026-01-30", freq="3D", tz="UTC"))
    replay = list(pd.date_range("2026-01-31", "2026-02-28", freq="D", tz="UTC"))
    return history + development + holdout + replay


def validate(progress=None, candidates=None, months=None):
    cfg = project()
    weather = cached_weather()
    obs = observations()
    candidates = candidates or CANDIDATES
    if any(c not in CANDIDATES for c in candidates):
        raise ValueError("Unregistered validation candidate")
    months = months or list(range(1, 13))
    scored, fold_reports = [], []
    for month in months:
        cutoff = pd.Timestamp(year=2025, month=month, day=1, tz="UTC")
        end = cutoff + pd.offsets.MonthBegin(1)
        train = training_table(weather, obs, cutoff)
        test = weather[(weather.origin >= cutoff) & (weather.origin < end)].reset_index(drop=True)
        if test.empty or train.empty:
            fold_reports.append({"month": f"2025-{month:02d}", "status": "unavailable", "reason": "no weather"})
            continue
        test = test.merge(obs.loc[obs.eligible, ["site_id", "target_time", "power"]],
                          on=["site_id", "target_time"], how="left", validate="many_to_one")
        for kind in candidates:
            model = PowerModel(kind).fit(train, cutoff)
            prediction = model.predict(test)
            result = pd.concat([test, prediction], axis=1)
            result["model"] = kind
            result["fold"] = cutoff.strftime("%Y-%m")
            scored.append(result[["site_id", "origin", "target_time", "lead_hours", "power", "prediction", "model", "fold"]])
            for site, group in result.groupby("site_id"):
                fold_reports.append({"month": cutoff.strftime("%Y-%m"), "site_id": site, "model": kind,
                                     "status": "ok", "origins": int(group.origin.nunique()),
                                     "train_rows": int((train.site_id == site).sum()), **metrics(group)})
            if progress:
                progress(cutoff.strftime("%Y-%m"), kind)
    if not scored:
        raise ValueError("No validation folds; fetch historical weather first")
    all_scores = pd.concat(scored, ignore_index=True)
    # All candidates are evaluated on the identical target mask; each site/month has equal weight.
    summaries = []
    for kind in candidates:
        valid = [r for r in fold_reports if r.get("model") == kind and r.get("rmse") is not None]
        if valid:
            summaries.append({"model": kind, "macro_rmse": float(np.mean([r["rmse"] for r in valid])),
                              "macro_mae": float(np.mean([r["mae"] for r in valid])),
                              "macro_bias": float(np.mean([r["bias"] for r in valid])),
                              "fold_site_count": len(valid), "scored_rows": sum(r["scored_rows"] for r in valid)})
    if not summaries:
        raise ValueError("Validation has no observed targets")
    best = min(summaries, key=lambda r: r["macro_rmse"])
    near = [r for r in summaries if r["macro_rmse"] <= best["macro_rmse"]*1.01]
    selected = min(near, key=lambda r: CANDIDATES.index(r["model"]))["model"]
    run_id = f"validation-{now():%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    root = data_root() / "evaluations" / run_id
    write_frame(root / "predictions.parquet", all_scores)
    report = {"id": run_id, "created_at": iso(now()), "config_hash": cfg.fingerprint,
              "mode": "monthly_blackout_weather_only", "aggregation": "equal_weight_site_month_macro_RMSE",
              "candidate_selection": "simplest model within 1% of lowest macro RMSE",
              "selected_model": selected, "summaries": summaries, "folds": fold_reports,
              "origin_sampling": "actual cached origins; see fold origin counts",
              "january_holdout_used_for_selection": False}
    write_json(root / "report.json", report)
    write_json(data_root() / "evaluations" / "selected.json", report)
    return report


def train_final():
    cfg = project()
    selection = read_json(data_root() / "evaluations" / "selected.json")
    if selection["config_hash"] != cfg.fingerprint:
        raise ValueError("Validation contract changed; revalidate")
    weather, obs = cached_weather(), observations()
    kind = selection["selected_model"]
    cutoff = utc(cfg.training_cutoff)
    root = data_root() / "evaluations" / selection["id"]
    # A persisted holdout is opened once per frozen development selection.
    holdout_path = root / "january_holdout.json"
    if holdout_path.exists():
        holdout = read_json(holdout_path)
    else:
        holdout_start = utc("2026-01-01T00:00:00Z")
        hold_model = PowerModel(kind).fit(training_table(weather, obs, holdout_start), holdout_start, with_intervals=True)
        hold_weather = weather[(weather.origin >= holdout_start) & (weather.origin < cutoff)].reset_index(drop=True)
        hold_weather = hold_weather.merge(obs.loc[obs.eligible, ["site_id", "target_time", "power"]],
                                          on=["site_id", "target_time"], how="left", validate="many_to_one")
        if hold_weather.empty:
            raise ValueError("Fetch January holdout weather before final training")
        hold_pred = pd.concat([hold_weather, hold_model.predict(hold_weather)], axis=1)
        holdout = {"opened_at": iso(now()), "model_frozen_before_holdout": kind,
                   "selection_id": selection["id"], "origins": int(hold_weather.origin.nunique()),
                   "sites": {s: metrics(g) for s, g in hold_pred.groupby("site_id")},
                   "used_for_selection": False}
        write_frame(root / "january_predictions.parquet", hold_pred)
        write_json(holdout_path, holdout)
    train = training_table(weather, obs, cutoff)
    model = PowerModel(kind).fit(train, cutoff, with_intervals=True)
    version = model.save({"selection_id": selection["id"], "january_holdout": holdout,
                          "time_metadata_confirmed": cfg.time_metadata_confirmed,
                          "availability_lag_confirmed": cfg.weather_release_lag_confirmed})
    write_json(data_root() / "models" / "active.json", {"version": version, "selected_at": iso(now())})
    return model.card
