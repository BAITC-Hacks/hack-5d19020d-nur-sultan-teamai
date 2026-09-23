from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


def demo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_env() -> None:
    """Load secrets from local .env files (never committed).

    Search order (first wins for each key; later files only fill gaps):
    1) demo/.env
    2) repo-root .env
    3) cwd/.env and parents up to filesystem root (agent-friendly)
    """
    root = demo_root()
    repo = root.parent
    candidates: list[Path] = [root / ".env", repo / ".env"]
    cwd = Path.cwd().resolve()
    for folder in [cwd, *cwd.parents]:
        candidates.append(folder / ".env")
        if folder == repo or folder == folder.parent:
            break
    seen: set[Path] = set()
    for path in candidates:
        path = path.resolve()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        load_dotenv(path, override=False)


# Eager load so `import wind_demo` / CLI / API see keys even if callers forget load_env().
load_env()


class Site(BaseModel):
    turbine_id: str
    name: str = ""
    lat: float | None = None
    lon: float | None = None
    filename_contains: str = ""


class SitesConfig(BaseModel):
    sites: list[Site]


class TimeConfig(BaseModel):
    timezone_assumption: str = "UTC"
    interval_label: str = "start"
    sample_minutes: int = 10
    horizon_hours: int = 48
    schedule: str = "rolling_next_48"
    default_origin_hour_utc: int = 0
    telemetry_available_lag_hours: int = 1


class ModelsConfig(BaseModel):
    target: str = "power_normalized"
    features: list[str] = Field(default_factory=list)
    catboost: dict[str, Any] = Field(default_factory=dict)
    train: dict[str, Any] = Field(default_factory=dict)


class AgentConfig(BaseModel):
    llm_mode: str = "auto"
    openai_model: str = "gpt-4o-mini"
    nvidia_model: str = "meta/llama-3.1-8b-instruct"
    max_tool_steps: int = 6
    budget_usd_soft_limit: float = 5.0
    tools: list[str] = Field(default_factory=list)


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in {path}")
    return data


@lru_cache(maxsize=1)
def get_paths() -> dict[str, Path]:
    root = demo_root()
    return {
        "root": root,
        "configs": root / "configs",
        "raw": root / "data" / "raw",
        "fixtures": root / "data" / "fixtures",
        "processed": root / "data" / "processed",
        "models": root / "data" / "models",
        "traces": root / "data" / "traces",
        "exports": root / "data" / "exports",
    }


@lru_cache(maxsize=1)
def sites_config() -> SitesConfig:
    return SitesConfig.model_validate(_read_yaml(get_paths()["configs"] / "sites.yaml"))


@lru_cache(maxsize=1)
def time_config() -> TimeConfig:
    return TimeConfig.model_validate(_read_yaml(get_paths()["configs"] / "time.yaml"))


@lru_cache(maxsize=1)
def models_config() -> ModelsConfig:
    return ModelsConfig.model_validate(_read_yaml(get_paths()["configs"] / "models.yaml"))


@lru_cache(maxsize=1)
def agent_config() -> AgentConfig:
    cfg = AgentConfig.model_validate(_read_yaml(get_paths()["configs"] / "agent.yaml"))
    mode = os.getenv("WIND_DEMO_LLM_MODE")
    if mode:
        cfg.llm_mode = mode
    return cfg


def llm_mode() -> str:
    load_env()
    # Always prefer process env over cached YAML (cache can stick across tests).
    return os.getenv("WIND_DEMO_LLM_MODE") or agent_config().llm_mode


def clear_config_cache() -> None:
    get_paths.cache_clear()
    sites_config.cache_clear()
    time_config.cache_clear()
    models_config.cache_clear()
    agent_config.cache_clear()
