from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


ContractStatus = Literal["strict", "provisional", "synthetic"]
ScoreStatus = Literal["ok", "not_evaluated", "error"]


class HourlyObservation(BaseModel):
    turbine_id: str
    valid_start_utc: datetime
    valid_end_utc: datetime
    power_normalized: float | None
    wind_observed_ms: float | None = None
    temperature_observed_c: float | None = None
    sample_count: int
    eligible_target: bool
    observation_available_at_utc: datetime
    source: str


class WeatherPoint(BaseModel):
    turbine_id: str
    valid_start_utc: datetime
    wind_ms: float
    temperature_c: float
    u_ms: float | None = None
    v_ms: float | None = None


class WeatherSnapshot(BaseModel):
    snapshot_id: str
    provider: str
    origin_utc: datetime
    available_at_utc: datetime
    contract_status: ContractStatus
    points: list[WeatherPoint]
    notes: list[str] = Field(default_factory=list)


class ForecastRow(BaseModel):
    turbine_id: str
    forecast_origin_utc: datetime
    valid_start_utc: datetime
    valid_end_utc: datetime
    lead_hours: int
    power_point_normalized: float
    model_version: str
    weather_snapshot_id: str
    contract_status: ContractStatus


class ForecastBundle(BaseModel):
    origin_utc: datetime
    model_version: str
    contract_status: ContractStatus
    rows: list[ForecastRow]
    score_status: ScoreStatus = "not_evaluated"
    metrics: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class AgentTrace(BaseModel):
    created_at_utc: datetime
    mode: str
    goal: str
    steps: list[dict[str, Any]] = Field(default_factory=list)
    final_answer: str = ""
    blocked: list[str] = Field(default_factory=list)
