from pathlib import Path

import numpy as np
import pandas as pd

from .config import data_root, iso, now, project, raw_root
from .storage import sha256, write_frame, write_json

COLUMNS = ["source_id", "timestamp_local", "wind_observed", "power", "temperature_observed"]


def hourly_frame(raw, cfg, site_id):
    if raw.shape[1] != 5:
        raise ValueError(f"Expected five SCADA columns, got {raw.shape[1]}")
    frame = raw.copy()
    frame.columns = COLUMNS
    local = pd.to_datetime(frame.timestamp_local, errors="coerce")
    # Never guess repeated local clock hours across the 2024 Kazakhstan offset change.
    stamp = local.dt.tz_localize(cfg.timezone, ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC")
    if cfg.interval_label == "end":
        stamp = stamp - pd.Timedelta(minutes=10)
    frame["interval_start"] = stamp
    bad_time = stamp.isna() | (stamp.dt.minute % 10 != 0) | (stamp.dt.second != 0)
    numeric = ["wind_observed", "power", "temperature_observed"]
    frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="coerce")
    invalid_values = (~np.isfinite(frame[numeric])).any(axis=1) | ~frame.power.between(0, 1)
    invalid_values |= ~frame.wind_observed.between(0, 100)
    invalid_values |= ~frame.temperature_observed.between(-80, 70)
    duplicates = frame.interval_start.duplicated(keep=False) & stamp.notna()
    good = frame.loc[~(bad_time | invalid_values | duplicates)].copy()
    good["target_time"] = good.interval_start.dt.floor("h")
    result = good.groupby("target_time").agg(
        power=("power", "mean"), wind_observed=("wind_observed", "mean"),
        temperature_observed=("temperature_observed", "mean"), samples=("power", "size"))
    if good.empty:
        raise ValueError("No usable observations under the configured time contract")
    grid = pd.date_range(good.target_time.min(), good.target_time.max(), freq="h", tz="UTC")
    result = result.reindex(grid).rename_axis("target_time").reset_index()
    result["samples"] = result.samples.fillna(0).astype(int)
    result["eligible"] = result.samples.eq(6)
    result.loc[~result.eligible, numeric] = np.nan
    result["site_id"] = site_id
    result["obs_available_at"] = result.target_time + pd.Timedelta(hours=1, minutes=cfg.telemetry_delay_minutes)
    result["config_hash"] = cfg.fingerprint
    report = {
        "site_id": site_id, "input_rows": len(raw), "invalid_or_ambiguous_time_rows": int(bad_time.sum()),
        "invalid_numeric_rows": int(invalid_values.sum()), "duplicate_time_rows": int(duplicates.sum()),
        "full_hours": int(result.eligible.sum()), "partial_hours": int(result.samples.between(1, 5).sum()),
        "empty_hours": int(result.samples.eq(0).sum()),
        "first_interval_utc": iso(good.interval_start.min()), "last_interval_utc": iso(good.interval_start.max()),
        "power_min": float(good.power.min()), "power_max": float(good.power.max()),
    }
    return result, report


def ingest(source=None):
    cfg = project()
    folder = Path(source) if source else raw_root()
    frames, reports = [], []
    for site in cfg.sites:
        files = [p for p in folder.glob("*.xlsx") if site.filename_contains in p.name and not p.name.startswith("~$")]
        if len(files) != 1:
            raise ValueError(f"Expected one XLSX containing {site.filename_contains!r} in {folder}; found {len(files)}")
        path = files[0]
        raw = pd.read_excel(path, engine="openpyxl")
        frame, report = hourly_frame(raw, cfg, site.site_id)
        report.update(filename=path.name, sha256=sha256(path))
        frames.append(frame)
        reports.append(report)
    root = data_root() / "observations" / cfg.fingerprint
    write_frame(root / "hourly.parquet", pd.concat(frames, ignore_index=True))
    audit = {"created_at": iso(now()), "config": cfg.model_dump(), "config_hash": cfg.fingerprint,
             "sites": reports, "confirmed_time_metadata": cfg.time_metadata_confirmed}
    write_json(root / "audit.json", audit)
    return audit


def observations():
    path = data_root() / "observations" / project().fingerprint / "hourly.parquet"
    if not path.exists():
        raise FileNotFoundError("Run wind-agent ingest first (or re-ingest after changing the time configuration)")
    return pd.read_parquet(path)
