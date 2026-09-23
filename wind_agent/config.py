import hashlib
import json
import os
from pathlib import Path
from typing import Literal

import pandas as pd
from dotenv import load_dotenv
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]


def load_env() -> None:
    """Load local .env from repo root, then cwd/parents (agent-friendly). Never commit secrets."""
    candidates: list[Path] = [ROOT / ".env"]
    cwd = Path.cwd().resolve()
    for folder in [cwd, *cwd.parents]:
        candidates.append(folder / ".env")
        if folder == ROOT or folder == folder.parent:
            break
    seen: set[Path] = set()
    for path in candidates:
        path = path.resolve()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        load_dotenv(path, override=False)


load_env()


class Site(BaseModel):
    site_id: str
    label: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    coordinates_source: str
    filename_contains: str


class Project(BaseModel):
    schema_version: str
    timezone: str
    interval_label: Literal["start", "end"]
    time_metadata_confirmed: bool = False
    telemetry_delay_minutes: int = Field(default=10, ge=0)
    gfs_grid: Literal["1p00", "0p50", "0p25"] = "1p00"
    weather_release_lag_hours: int = Field(default=8, ge=6, le=24)
    weather_release_lag_confirmed: bool = False
    forecast_hours: int = Field(default=48, ge=24, le=48)
    training_cutoff: str
    sites: list[Site]

    @property
    def fingerprint(self):
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()[:16]


def project():
    path = Path(os.getenv("WIND_CONFIG", ROOT / "config" / "project.json"))
    return Project.model_validate_json(path.read_text(encoding="utf-8"))


def data_root():
    default = Path.home() / "Documents" / "Codex" / "wind-agent-runtime" / "data"
    path = Path(os.getenv("WIND_DATA_DIR", default))
    path.mkdir(parents=True, exist_ok=True)
    return path


def raw_root():
    return Path(os.getenv("WIND_RAW_DIR", ROOT.parent / "given"))


def utc(value):
    t = pd.Timestamp(value)
    if t.tzinfo is None:
        raise ValueError("Timestamp must include an explicit UTC offset, e.g. 2026-01-31T00:00Z")
    return t.tz_convert("UTC")


def iso(value):
    return utc(value).isoformat().replace("+00:00", "Z")


def now():
    return pd.Timestamp.now(tz="UTC")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()
