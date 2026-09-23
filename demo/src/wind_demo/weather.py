from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Protocol

import httpx
import numpy as np
import pandas as pd

from .config import Site, get_paths, sites_config, time_config
from .schemas import WeatherPoint, WeatherSnapshot
from .storage import ensure_dirs, write_frame, write_json


def _utc(ts: datetime | pd.Timestamp | str) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        return t.tz_localize("UTC")
    return t.tz_convert("UTC")


def power_curve(wind_ms: np.ndarray) -> np.ndarray:
    """Simple empirical normalized power curve for fixtures / synthetic demos."""
    v = np.asarray(wind_ms, dtype=float)
    out = np.zeros_like(v)
    cut_in, rated, cut_out = 3.0, 12.0, 25.0
    mid = (v >= cut_in) & (v < rated)
    out[mid] = ((v[mid] - cut_in) / (rated - cut_in)) ** 3
    out[(v >= rated) & (v < cut_out)] = 1.0
    return np.clip(out, 0, 1)


class WeatherProvider(Protocol):
    def fetch(self, origin: datetime, sites: list[Site], horizon_hours: int) -> WeatherSnapshot: ...


class FixtureProvider:
    """Deterministic weather from origin hash — works without coords/network."""

    def fetch(self, origin: datetime, sites: list[Site], horizon_hours: int) -> WeatherSnapshot:
        origin_ts = _utc(origin)
        seed = int(hashlib.sha256(str(origin_ts).encode()).hexdigest()[:8], 16)
        rng = np.random.default_rng(seed)
        points: list[WeatherPoint] = []
        for site in sites:
            base = 6.0 + (hash(site.turbine_id) % 5)
            for lead in range(1, horizon_hours + 1):
                valid = origin_ts + pd.Timedelta(hours=lead - 1)
                wind = float(np.clip(base + rng.normal(0, 1.5) + 0.3 * np.sin(lead / 6), 0.2, 22))
                temp = float(5 + 10 * np.sin((valid.dayofyear + lead) / 20) + rng.normal(0, 1))
                points.append(
                    WeatherPoint(
                        turbine_id=site.turbine_id,
                        valid_start_utc=valid.to_pydatetime(),
                        wind_ms=wind,
                        temperature_c=temp,
                        u_ms=-wind * 0.7,
                        v_ms=-wind * 0.3,
                    )
                )
        snap_id = f"fixture-{origin_ts.strftime('%Y%m%dT%H%M')}"
        return WeatherSnapshot(
            snapshot_id=snap_id,
            provider="fixture",
            origin_utc=origin_ts.to_pydatetime(),
            available_at_utc=origin_ts.to_pydatetime(),
            contract_status="synthetic",
            points=points,
            notes=["Synthetic weather; replace with Open-Meteo when lat/lon are set."],
        )


class OpenMeteoProvider:
    """Provisional forecast weather when coordinates exist."""

    BASE = "https://api.open-meteo.com/v1/forecast"

    def fetch(self, origin: datetime, sites: list[Site], horizon_hours: int) -> WeatherSnapshot:
        origin_ts = _utc(origin)
        missing = [s.turbine_id for s in sites if s.lat is None or s.lon is None]
        if missing:
            raise ValueError(f"Open-Meteo needs lat/lon for sites: {missing}")
        points: list[WeatherPoint] = []
        notes: list[str] = []
        with httpx.Client(timeout=30) as client:
            for site in sites:
                params = {
                    "latitude": site.lat,
                    "longitude": site.lon,
                    "hourly": "temperature_2m,wind_speed_10m,wind_direction_10m",
                    "wind_speed_unit": "ms",
                    "timezone": "UTC",
                    "forecast_days": 3,
                }
                r = client.get(self.BASE, params=params)
                r.raise_for_status()
                payload = r.json()
                times = pd.to_datetime(payload["hourly"]["time"], utc=True)
                winds = payload["hourly"]["wind_speed_10m"]
                temps = payload["hourly"]["temperature_2m"]
                dirs = payload["hourly"]["wind_direction_10m"]
                for lead in range(1, horizon_hours + 1):
                    valid = origin_ts + pd.Timedelta(hours=lead - 1)
                    # nearest hour
                    idx = int(np.argmin(np.abs((times - valid).total_seconds())))
                    wind = float(winds[idx])
                    temp = float(temps[idx])
                    direction = float(dirs[idx])
                    rad = np.deg2rad(direction)
                    u = float(-wind * np.sin(rad))
                    v = float(-wind * np.cos(rad))
                    points.append(
                        WeatherPoint(
                            turbine_id=site.turbine_id,
                            valid_start_utc=valid.to_pydatetime(),
                            wind_ms=wind,
                            temperature_c=temp,
                            u_ms=u,
                            v_ms=v,
                        )
                    )
                notes.append(f"Open-Meteo forecast for {site.turbine_id} at ({site.lat},{site.lon})")
        snap_id = f"openmeteo-{origin_ts.strftime('%Y%m%dT%H%M')}"
        return WeatherSnapshot(
            snapshot_id=snap_id,
            provider="open-meteo-forecast",
            origin_utc=origin_ts.to_pydatetime(),
            available_at_utc=datetime.now(timezone.utc),
            contract_status="provisional",
            points=points,
            notes=notes
            + [
                "Forecast API is provisional for historical as-of replay; "
                "true archive provenance is out of MVP scope."
            ],
        )


def get_provider() -> WeatherProvider:
    sites = sites_config().sites
    if all(s.lat is not None and s.lon is not None for s in sites):
        return OpenMeteoProvider()
    return FixtureProvider()


def fetch_and_cache(origin: datetime) -> WeatherSnapshot:
    ensure_dirs()
    cfg = time_config()
    sites = sites_config().sites
    provider = get_provider()
    snap = provider.fetch(origin, sites, cfg.horizon_hours)
    paths = get_paths()
    cache_dir = paths["processed"] / "weather"
    cache_dir.mkdir(parents=True, exist_ok=True)
    rows = [p.model_dump() for p in snap.points]
    frame = pd.DataFrame(rows)
    write_frame(cache_dir / f"{snap.snapshot_id}.parquet", frame)
    write_json(cache_dir / f"{snap.snapshot_id}.json", snap.model_dump())
    return snap


def snapshot_to_frame(snap: WeatherSnapshot) -> pd.DataFrame:
    df = pd.DataFrame([p.model_dump() for p in snap.points])
    df["valid_start_utc"] = pd.to_datetime(df["valid_start_utc"], utc=True)
    return df
