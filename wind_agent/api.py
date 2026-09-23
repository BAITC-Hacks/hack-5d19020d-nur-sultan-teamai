import hmac
import json
import os
import re
import secrets

import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator

from .config import data_root, iso, now, project, utc
from .forecast import list_forecasts
from .jobs import enqueue, get_job, list_jobs, retry_job
from .llm import usage_summary
from .storage import events, read_json

app = FastAPI(title="WIND AGENT", version="0.1.0", description="Local API for auditable wind power forecasts")


def local_token():
    configured = os.getenv("WIND_API_TOKEN")
    if configured:
        return configured
    path = data_root() / "api-token"
    try:
        with path.open("x", encoding="ascii") as f:
            token = secrets.token_urlsafe(32)
            f.write(token)
            return token
    except FileExistsError:
        return path.read_text(encoding="ascii").strip()


def authorize(authorization: str | None = Header(default=None)):
    if not authorization or not hmac.compare_digest(authorization, "Bearer " + local_token()):
        raise HTTPException(401, "A local bearer token is required for write operations")


class ForecastRequest(BaseModel):
    origin: str
    provider: str = Field(default="offline", pattern="^(offline|openai|nvidia)$")
    strict: bool = False

    @field_validator("origin")
    @classmethod
    def origin_is_aware(cls, value):
        t = utc(value)
        if t != t.floor("h"):
            raise ValueError("Origin must be an exact UTC hour")
        return iso(t)


class ReplayRequest(BaseModel):
    start: str = "2026-01-31T00:00:00Z"
    end: str = "2026-02-28T00:00:00Z"
    strict: bool = False

    @field_validator("start", "end")
    @classmethod
    def is_aware(cls, value):
        t = utc(value)
        if t != t.floor("D"):
            raise ValueError("Replay origins must be UTC midnight")
        return iso(t)


def artifact_dir(kind, identifier):
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", identifier):
        raise HTTPException(400, "Invalid artifact ID")
    path = data_root() / kind / identifier
    if not path.is_dir():
        raise HTTPException(404, "Artifact not found")
    return path


@app.exception_handler(FileNotFoundError)
def missing_handler(request, exc):
    return JSONResponse(status_code=409, content={"detail": "Required data/model not ready; run ingest, weather, validate and train"})


@app.exception_handler(ValueError)
def value_handler(request, exc):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.1.0", "time": iso(now())}


@app.get("/ready")
def ready():
    cfg = project()
    workers = []
    for path in (data_root() / "workers").glob("*.json"):
        try:
            item = read_json(path)
            if (now()-utc(item["seen_at"])).total_seconds() < 65:
                workers.append(item)
        except (OSError, ValueError, KeyError):
            continue
    checks = {"observations": (data_root()/"observations"/cfg.fingerprint/"hourly.parquet").exists(),
              "model": False, "worker": bool(workers)}
    try:
        from .models import active_model
        active_model()
        checks["model"] = True
    except (FileNotFoundError, ValueError, KeyError):
        pass
    result = {"ready": all(checks.values()), "checks": checks, "workers": workers,
              "strict_metadata_ready": cfg.time_metadata_confirmed and cfg.weather_release_lag_confirmed}
    return JSONResponse(status_code=200 if result["ready"] else 503, content=result)


@app.get("/sites")
def sites():
    return project().model_dump()


@app.post("/forecast-jobs", status_code=202, dependencies=[Depends(authorize)])
def forecast_job(body: ForecastRequest):
    if body.strict and not (project().time_metadata_confirmed and project().weather_release_lag_confirmed):
        raise HTTPException(409, "Strict mode requires confirmed time metadata and weather release policy")
    return enqueue("forecast", body.model_dump())


@app.post("/replay-jobs", status_code=202, dependencies=[Depends(authorize)])
def replay_job(body: ReplayRequest):
    if utc(body.end) < utc(body.start) or (utc(body.end)-utc(body.start)).days > 366:
        raise HTTPException(422, "Replay range must span 0..366 days")
    return enqueue("replay", body.model_dump())


@app.get("/jobs")
def jobs():
    return list_jobs()


@app.get("/jobs/{job_id}")
def job(job_id: str):
    try:
        return get_job(job_id)
    except KeyError:
        raise HTTPException(404, "Job not found") from None


@app.post("/jobs/{job_id}/retry", dependencies=[Depends(authorize)])
def retry(job_id: str):
    return retry_job(job_id)


@app.get("/traces")
def traces(job_id: str | None = None):
    return events(job_id)


@app.get("/forecasts")
def forecasts():
    return list_forecasts()


@app.get("/forecasts/{forecast_id}")
def forecast(forecast_id: str):
    path = artifact_dir("forecasts", forecast_id)
    rows = pd.read_parquet(path / "forecast.parquet")
    return {"manifest": read_json(path / "manifest.json"), "rows": json.loads(rows.to_json(orient="records", date_format="iso"))}


@app.get("/exports/{forecast_id}")
def export(forecast_id: str):
    return FileResponse(artifact_dir("forecasts", forecast_id) / "forecast.csv", media_type="text/csv", filename=f"{forecast_id}.csv")


@app.get("/metrics")
def scores():
    path = data_root() / "evaluations" / "selected.json"
    if not path.exists():
        return {"available": False, "reason": "Validation has not run"}
    report = read_json(path)
    holdout = path.parent / report["id"] / "january_holdout.json"
    return {"available": True, "validation": report, "holdout": read_json(holdout) if holdout.exists() else None,
            "february": {"available": False, "reason": "No supplied February power actuals"}}


@app.get("/audit")
def audit():
    return read_json(data_root() / "observations" / project().fingerprint / "audit.json")


@app.get("/usage")
def usage():
    return {"ledger": usage_summary(), "budget_usd": float(os.getenv("WIND_LLM_BUDGET_USD", "2")),
            "note": "Local estimates/reservations, not a provider balance. NVIDIA price unverified."}
