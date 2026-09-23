"""Configuration loading with validation and no implicit assumptions."""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from wind_agent.errors import ConfigurationError
from wind_agent.schemas import TimestampSemantics


class SiteConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turbine_id: str
    coordinate_source: str
    latitude: float | None = None
    longitude: float | None = None
    coordinate_status: str
    scada_timezone: str | None = None
    timestamp_semantics: TimestampSemantics | None = None
    availability_delay_minutes: int | None = None


class SitesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    sites: list[SiteConfig]


def load_sites(path: Path) -> SitesConfig:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return SitesConfig.model_validate(raw)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise ConfigurationError(f"could not load sites configuration at {path}: {exc}") from exc
