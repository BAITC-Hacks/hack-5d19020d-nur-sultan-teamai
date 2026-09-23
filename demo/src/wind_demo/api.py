from __future__ import annotations

from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .agent.graph import run_agent
from .config import load_env
from .forecast import export_submission, run_forecast
from .ingest import ingest, load_hourly
from .storage import ensure_dirs
from .train import train_model

load_env()
ensure_dirs()

app = FastAPI(title="Wind Demo MVP", version="0.1.0")


class ForecastRequest(BaseModel):
    origin: Optional[str] = None
    turbine_ids: Optional[list[str]] = None


class AgentRequest(BaseModel):
    goal: str = Field(default="Audit data then run a 48h forecast and summarize.")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ingest")
def api_ingest() -> dict[str, Any]:
    return ingest(prefer_raw=True)


@app.post("/train")
def api_train(max_origins: int = 40) -> dict[str, Any]:
    return train_model(max_origins=max_origins)


@app.post("/forecast")
def api_forecast(body: ForecastRequest) -> dict[str, Any]:
    bundle = run_forecast(origin=body.origin, turbine_ids=body.turbine_ids)
    return bundle.model_dump()


@app.post("/replay")
def api_replay(body: ForecastRequest) -> dict[str, Any]:
    """Alias of forecast for demo clarity (same as-of pipeline)."""
    return api_forecast(body)


@app.post("/export")
def api_export(body: ForecastRequest) -> dict[str, Any]:
    return export_submission(origin=body.origin)


@app.post("/agent/run")
def api_agent(body: AgentRequest) -> dict[str, Any]:
    try:
        trace = run_agent(body.goal)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return trace.model_dump()


@app.get("/audit")
def api_audit() -> dict[str, Any]:
    hourly = load_hourly()
    return {
        "n_rows": int(len(hourly)),
        "turbines": sorted(hourly["turbine_id"].unique().tolist()),
        "last_utc": str(hourly["valid_start_utc"].max()),
        "feb_2026_rows": int(
            ((hourly["valid_start_utc"] >= "2026-02-01") & (hourly["valid_start_utc"] < "2026-03-01")).sum()
        ),
    }
