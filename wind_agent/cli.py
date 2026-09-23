import json
from pathlib import Path

import typer

from .config import data_root, iso, now, project
from .storage import write_json

app = typer.Typer(no_args_is_help=True, help="WIND AGENT — reproducible normalized power forecasting")


def show(value):
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))


@app.command()
def doctor():
    import importlib.metadata
    import os

    from .config import raw_root
    show({"config_hash": project().fingerprint, "data_dir": str(data_root()), "raw_dir": str(raw_root()),
          "raw_exists": raw_root().is_dir(), "api_keys_present": {name: bool(os.getenv(name)) for name in ["OPENAI_API_KEY", "NVIDIA_API_KEY"]},
          "assumptions": project().model_dump(),
          "versions": {name: importlib.metadata.version(name) for name in ["pandas", "catboost", "eccodes", "fastapi", "streamlit", "langgraph"]}})


@app.command()
def ingest(source: Path | None = None):
    from .ingest import ingest as action
    show(action(source))


@app.command()
def weather(origin: str | None = None, profile: str = "mvp"):
    from .evaluation import monthly_origins
    from .weather import fetch_many, fetch_weather
    if origin:
        _, manifest = fetch_weather(origin)
        show({k: v for k, v in manifest.items() if k != "objects"})
    else:
        result = fetch_many(monthly_origins(profile), lambda o, s, d, t: typer.echo(f"{d}/{t} {o:%Y-%m-%d} {s}"))
        show(result)
        if result["failed"]:
            raise typer.Exit(1)


@app.command()
def validate():
    from .evaluation import validate as action
    result = action(progress=lambda month, model: typer.echo(f"Validated {month} {model}"))
    show({k: v for k, v in result.items() if k != "folds"})


@app.command()
def train():
    from .evaluation import train_final
    show(train_final())


@app.command()
def forecast(origin: str = "2026-01-31T00:00Z", provider: str = "offline", strict: bool = False):
    from .agent import run_agent
    show(run_agent(origin, provider=provider, strict=strict))


@app.command()
def replay(start: str = "2026-01-31T00:00Z", end: str = "2026-02-28T00:00Z", strict: bool = False):
    from .forecast import replay as action
    show(action(start, end, strict, progress=lambda o, f: typer.echo(f"{o} {f}")))


@app.command()
def worker(once: bool = False):
    from .jobs import worker as action
    action(once)


@app.command()
def serve(port: int = 8000):
    import uvicorn
    uvicorn.run("wind_agent.api:app", host="127.0.0.1", port=port)


@app.command("provider-probe")
def provider_probe(provider: str = "openai"):
    from .llm import choose_tool
    show(choose_tool({"task": "Verify tool calling only; no forecast or spending beyond this single call"},
                      {"get_quality_report": "Read input quality report"}, provider))


@app.command("run-all")
def run_all(profile: str = "mvp"):
    from .evaluation import monthly_origins, train_final
    from .evaluation import validate as validate_action
    from .forecast import replay as replay_action
    from .ingest import ingest as ingest_action
    from .storage import read_json
    from .weather import fetch_many
    cfg = project()
    status_path = data_root() / "pipeline.json"
    status = read_json(status_path) if status_path.exists() else {}
    if status.get("config_hash") != cfg.fingerprint or status.get("profile") != profile:
        status = {"config_hash": cfg.fingerprint, "profile": profile, "completed": []}
    def step(name, action):
        if name in status["completed"]:
            typer.echo(f"Resume: {name} already complete")
            return
        status.update(stage=name, state="running", updated_at=iso(now()))
        write_json(status_path, status)
        typer.echo(f"Starting {name}")
        try:
            result = action()
            if name == "weather" and result["failed"]:
                raise RuntimeError(f"Weather failed at {len(result['failed'])} origins; rerun to resume cache")
            status["completed"].append(name)
            status.update(state="completed", updated_at=iso(now()))
            write_json(status_path, status)
        except Exception as exc:
            status.update(state="failed", error=str(exc), updated_at=iso(now()))
            write_json(status_path, status)
            raise
    step("ingest", ingest_action)
    step("weather", lambda: fetch_many(monthly_origins(profile), lambda o, s, d, t: typer.echo(f"{d}/{t} {o:%Y-%m-%d} {s}")))
    step("validation", lambda: validate_action(progress=lambda m, k: typer.echo(f"Validated {m} {k}")))
    step("train", train_final)
    step("replay", replay_action)
    show(status)


@app.command("release-check")
def release_check():
    from .release import release_check as action
    show(action())


if __name__ == "__main__":
    app()
