from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .config import get_paths, sites_config, time_config
from .storage import ensure_dirs, sha256_file, write_frame, write_json


def _normalize_columns(raw: pd.DataFrame) -> pd.DataFrame:
    cols = {c.lower().strip(): c for c in raw.columns}
    mapping = {}
    for key, aliases in {
        "timestamp": ["timestamp", "timestamp_local", "time", "datetime", "date"],
        "power": ["power", "power_normalized", "p", "active_power"],
        "wind": ["wind", "wind_observed", "wind_speed", "ws"],
        "temperature": ["temperature", "temperature_observed", "temp", "t"],
    }.items():
        for alias in aliases:
            if alias in cols:
                mapping[key] = cols[alias]
                break
    if "timestamp" not in mapping or "power" not in mapping:
        if raw.shape[1] >= 4:
            # Fallback: id, timestamp, wind, power, temperature
            names = list(raw.columns)
            mapping = {
                "timestamp": names[1],
                "wind": names[2],
                "power": names[3],
                "temperature": names[4] if len(names) > 4 else names[3],
            }
        else:
            raise ValueError(f"Cannot map SCADA columns: {list(raw.columns)}")
    out = pd.DataFrame(
        {
            "timestamp_local": pd.to_datetime(raw[mapping["timestamp"]], errors="coerce"),
            "power": pd.to_numeric(raw[mapping["power"]], errors="coerce"),
            "wind_observed": pd.to_numeric(raw.get(mapping.get("wind", mapping["power"])), errors="coerce")
            if "wind" in mapping
            else np.nan,
            "temperature_observed": pd.to_numeric(
                raw[mapping["temperature"]], errors="coerce"
            )
            if "temperature" in mapping
            else np.nan,
        }
    )
    return out


def hourlyize(raw: pd.DataFrame, turbine_id: str, source: str) -> tuple[pd.DataFrame, dict]:
    cfg = time_config()
    frame = _normalize_columns(raw)
    stamp = pd.to_datetime(frame["timestamp_local"], utc=False)
    # Provisional: treat naive as UTC
    stamp = stamp.dt.tz_localize("UTC", ambiguous="NaT", nonexistent="NaT")
    if cfg.interval_label == "end":
        stamp = stamp - pd.Timedelta(minutes=cfg.sample_minutes)
    frame["interval_start"] = stamp
    bad = stamp.isna()
    frame["power"] = pd.to_numeric(frame["power"], errors="coerce")
    invalid = (~np.isfinite(frame["power"])) | ~frame["power"].between(0, 1.05)
    good = frame.loc[~(bad | invalid)].copy()
    if good.empty:
        raise ValueError(f"No usable rows for {turbine_id}")
    good["target_time"] = good["interval_start"].dt.floor("h")
    agg = good.groupby("target_time").agg(
        power_normalized=("power", "mean"),
        wind_observed_ms=("wind_observed", "mean"),
        temperature_observed_c=("temperature_observed", "mean"),
        sample_count=("power", "size"),
    )
    expected = max(1, 60 // cfg.sample_minutes)
    grid = pd.date_range(good["target_time"].min(), good["target_time"].max(), freq="h", tz="UTC")
    agg = agg.reindex(grid).rename_axis("valid_start_utc").reset_index()
    agg["sample_count"] = agg["sample_count"].fillna(0).astype(int)
    agg["eligible_target"] = agg["sample_count"] >= expected
    for col in ("power_normalized", "wind_observed_ms", "temperature_observed_c"):
        agg.loc[~agg["eligible_target"], col] = np.nan
    agg["valid_end_utc"] = agg["valid_start_utc"] + pd.Timedelta(hours=1)
    lag = pd.Timedelta(hours=cfg.telemetry_available_lag_hours)
    agg["observation_available_at_utc"] = agg["valid_end_utc"] + lag
    agg["turbine_id"] = turbine_id
    agg["source"] = source
    report = {
        "turbine_id": turbine_id,
        "source": source,
        "input_rows": int(len(frame)),
        "usable_rows": int(len(good)),
        "full_hours": int(agg["eligible_target"].sum()),
        "first_utc": str(agg["valid_start_utc"].min()),
        "last_utc": str(agg["valid_start_utc"].max()),
    }
    return agg, report


def _load_raw_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path, engine="openpyxl")
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    raise ValueError(f"Unsupported input: {path}")


def ingest(prefer_raw: bool = True) -> dict:
    ensure_dirs()
    paths = get_paths()
    sites = sites_config().sites
    frames: list[pd.DataFrame] = []
    reports: list[dict] = []

    raw_files = list(paths["raw"].glob("*.xlsx")) + list(paths["raw"].glob("*.csv"))
    raw_files = [p for p in raw_files if not p.name.startswith("~$")]

    if prefer_raw and raw_files:
        for site in sites:
            matches = [p for p in raw_files if site.filename_contains.lower() in p.name.lower()]
            if not matches:
                continue
            path = sorted(matches)[0]
            frame, report = hourlyize(_load_raw_table(path), site.turbine_id, source=path.name)
            report["sha256"] = sha256_file(path)
            frames.append(frame)
            reports.append(report)
        mode = "raw"
    else:
        for site in sites:
            fixture = paths["fixtures"] / f"scada_{site.turbine_id}.csv"
            if not fixture.exists():
                raise FileNotFoundError(f"Missing fixture {fixture}; run scripts/make_fixtures.py")
            frame, report = hourlyize(_load_raw_table(fixture), site.turbine_id, source=fixture.name)
            report["sha256"] = sha256_file(fixture)
            frames.append(frame)
            reports.append(report)
        mode = "fixture"

    if not frames:
        # Auto-fallback to fixtures
        return ingest(prefer_raw=False)

    hourly = pd.concat(frames, ignore_index=True)
    out = paths["processed"] / "hourly.parquet"
    write_frame(out, hourly)
    audit = {
        "mode": mode,
        "n_rows": int(len(hourly)),
        "sites": reports,
        "path": str(out),
    }
    write_json(paths["processed"] / "audit.json", audit)
    return audit


def load_hourly() -> pd.DataFrame:
    path = get_paths()["processed"] / "hourly.parquet"
    if not path.exists():
        ingest()
    df = pd.read_parquet(path)
    for col in ("valid_start_utc", "valid_end_utc", "observation_available_at_utc"):
        df[col] = pd.to_datetime(df[col], utc=True)
    return df
