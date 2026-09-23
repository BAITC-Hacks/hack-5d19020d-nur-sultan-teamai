from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from wind_agent import agent, forecast, jobs, llm
from wind_agent.api import app
from wind_agent.config import data_root, utc
from wind_agent.models import PowerModel
from wind_agent.storage import db, read_json, write_json


@pytest.fixture
def registered(training_data, cfg, monkeypatch):
    model = PowerModel("train_mean").fit(training_data, "2025-01-01T00:00Z")
    version = model.save()
    write_json(data_root()/"models"/"active.json", {"version":version})
    weather = training_data.groupby("site_id").head(48).copy().reset_index(drop=True)
    origin = utc("2026-01-31T00:00Z")
    for site in cfg.sites:
        mask = weather.site_id == site.site_id
        weather.loc[mask, "target_time"] = pd.date_range(origin, periods=48, freq="h")
        weather.loc[mask, "lead_hours"] = list(range(48))
    weather["origin"] = origin
    weather["run_init"] = origin-pd.Timedelta(hours=12)
    weather["weather_available_at"] = origin-pd.Timedelta(hours=4)
    weather = weather.drop(columns=["power", "sample_weight", "obs_available_at"])
    manifest = {"sha256":"fixture", "run_init":"2026-01-30T12:00:00Z", "available_at":"2026-01-30T20:00:00Z", "grid":"1p00"}
    monkeypatch.setattr(forecast, "fetch_weather", lambda _: (weather.copy(), manifest.copy()))
    write_json(data_root()/"observations"/cfg.fingerprint/"audit.json",
               {"sites":[{"site_id":"turbine_1", "full_hours":400, "partial_hours":0, "empty_hours":0}], "confirmed_time_metadata":False})
    return model


def test_forecast_is_96_rows_and_idempotent(registered):
    first, a = forecast.predict_origin("2026-01-31T00:00Z")
    second, b = forecast.predict_origin("2026-01-31T00:00Z")
    assert len(first) == 96 and first.provisional.all()
    assert a["forecast_id"] == b["forecast_id"]
    pd.testing.assert_frame_equal(first, second)


def test_strict_export_blocked(registered):
    with pytest.raises(ValueError, match="Strict export blocked"):
        forecast.predict_origin("2026-01-31T00:00Z", strict=True)


def test_future_model_refused(registered):
    with pytest.raises(ValueError, match="trained after"):
        forecast.predict_origin("2024-01-31T00:00Z")


def test_forecast_corruption_not_reused(registered):
    _, manifest = forecast.predict_origin("2026-01-31T00:00Z")
    (data_root()/"forecasts"/manifest["forecast_id"]/"forecast.parquet").write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksum"):
        forecast.predict_origin("2026-01-31T00:00Z")


def test_offline_agent_completes_real_tools(registered):
    result = agent.run_agent("2026-01-31T00:00Z")
    assert result["supervisor_decisions"] == 4
    assert result["forecast"]["rows"] == 96
    assert not result["llm_verified"]


def test_provider_failure_preserves_numerical_workflow(registered, monkeypatch):
    def fail(*args):
        raise llm.ProviderUnavailable("test provider outage")
    monkeypatch.setattr(agent, "choose_tool", fail)
    result = agent.run_agent("2026-01-31T00:00Z", provider="openai")
    assert result["degraded"] and result["forecast"]["rows"] == 96


def test_agent_cannot_finish_before_prediction():
    assert "finish" not in agent.allowed_actions({})
    assert "run_forecast" not in agent.allowed_actions({})


def test_injected_action_rejected_before_execution():
    with pytest.raises(ValueError, match="Disallowed"):
        agent._execute({"decision":{"action":"shell"}})


def test_job_dedup_and_worker_result(registered):
    payload = {"origin":"2026-01-31T00:00Z", "provider":"offline"}
    one = jobs.enqueue("forecast", payload)
    two = jobs.enqueue("forecast", payload)
    assert one["id"] == two["id"]
    assert jobs.process_one()
    assert jobs.get_job(one["id"])["state"] == "succeeded"
    assert not jobs.process_one()


def test_expired_worker_lease_reclaimed(registered):
    job = jobs.enqueue("forecast", {"origin":"2026-01-31T00:00Z"})
    assert jobs.claim("dead-worker")["id"] == job["id"]
    with db() as conn:
        conn.execute("UPDATE jobs SET lease_until=? WHERE id=?", ("2000-01-01T00:00:00Z", job["id"]))
    assert jobs.process_one("new-worker")
    assert jobs.get_job(job["id"])["attempts"] == 2


def test_queue_claim_has_only_one_owner(registered):
    jobs.enqueue("forecast", {"origin":"2026-01-31T00:00Z"})
    with ThreadPoolExecutor(4) as pool:
        claimed = list(pool.map(jobs.claim, ["a", "b", "c", "d"]))
    assert sum(x is not None for x in claimed) == 1


def test_missing_credentials_do_not_spend():
    with pytest.raises(llm.ProviderUnavailable, match="not configured"):
        llm.choose_tool({}, {"finish":"finish"})
    assert llm.usage_summary() == []


def test_credit_redemption_url_is_not_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "https://example.invalid/redeem")
    with pytest.raises(llm.ProviderUnavailable, match="contains a URL"):
        llm.choose_tool({}, {"finish":"finish"})


def test_llm_spending_cap_before_network(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    monkeypatch.setenv("WIND_LLM_BUDGET_USD", "0")
    with pytest.raises(llm.ProviderUnavailable, match="budget"):
        llm.choose_tool({}, {"finish":"finish"})


def test_llm_tool_schema_and_usage(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    class Response:
        status_code = 200
        def json(self):
            return {"output":[{"type":"function_call", "name":"get_quality_report", "arguments":'{"reason":"test"}'}],
                    "usage":{"input_tokens":100, "output_tokens":50}}
    monkeypatch.setattr(llm.httpx, "post", lambda *args, **kwargs: Response())
    result = llm.choose_tool({}, {"get_quality_report":"read"})
    assert result["action"] == "get_quality_report"
    assert llm.usage_summary()[0]["accounted_usd"] == pytest.approx(.0003)


def test_llm_forbidden_action_is_rejected(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    class Response:
        status_code = 200
        def json(self):
            return {"output":[{"type":"function_call", "name":"delete_files", "arguments":'{"reason":"test"}'}]}
    monkeypatch.setattr(llm.httpx, "post", lambda *args, **kwargs: Response())
    with pytest.raises(llm.ProviderUnavailable, match="allowlist"):
        llm.choose_tool({}, {"finish":"finish"})


def test_api_health_and_write_auth(registered):
    client = TestClient(app)
    assert client.get("/health").status_code == 200
    assert client.post("/forecast-jobs", json={"origin":"2026-01-31T00:00Z"}).status_code == 401
    headers = {"Authorization":"Bearer unit-test-only-token"}
    response = client.post("/forecast-jobs", json={"origin":"2026-01-31T00:00Z"}, headers=headers)
    assert response.status_code == 202
    assert client.get("/jobs/"+response.json()["id"]).json()["state"] == "queued"


def test_api_rejects_naive_and_strict_timestamps(registered):
    client = TestClient(app)
    headers = {"Authorization":"Bearer unit-test-only-token"}
    assert client.post("/forecast-jobs", json={"origin":"2026-01-31"}, headers=headers).status_code == 422
    assert client.post("/forecast-jobs", json={"origin":"2026-01-31T00:00Z", "strict":True}, headers=headers).status_code == 409


def test_api_export_matches_saved_csv(registered):
    _, manifest = forecast.predict_origin("2026-01-31T00:00Z")
    response = TestClient(app).get("/exports/"+manifest["forecast_id"])
    assert response.status_code == 200
    assert "normalized" not in response.text.splitlines()[0] or "prediction" in response.text
    expected = (data_root()/"forecasts"/manifest["forecast_id"]/"forecast.csv").read_bytes()
    assert response.content == expected


def test_api_missing_job_is_404():
    assert TestClient(app).get("/jobs/missing").status_code == 404


def test_api_no_february_score_invention():
    write_json(data_root()/"evaluations"/"selected.json", {"id":"test"})
    assert TestClient(app).get("/metrics").json()["february"]["available"] is False


def test_atomic_json_has_no_partial_files(tmp_path):
    path = tmp_path/"record.json"
    write_json(path, {"status":"ok"})
    assert read_json(path) == {"status":"ok"}
    assert list(tmp_path.glob("*.tmp")) == []


def test_failed_job_retry_is_explicit(registered):
    job = jobs.enqueue("forecast", {"origin":"2024-01-01T00:00Z"})
    jobs.process_one()
    assert jobs.get_job(job["id"])["state"] == "failed"
    assert jobs.retry_job(job["id"])["state"] == "queued"


def test_completion_requires_both_quality_and_model(registered):
    state = {"inspected_quality":True}
    assert list(agent.allowed_actions(state)) == ["get_model_card"]
