from __future__ import annotations

from typing import Optional

import typer

from .agent.graph import run_agent
from .config import load_env
from .fixtures import make_fixtures
from .forecast import export_submission, run_forecast
from .ingest import ingest
from .storage import ensure_dirs
from .train import train_model

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Wind Demo MVP CLI")


@app.callback()
def _root() -> None:
    load_env()
    ensure_dirs()


@app.command("make-fixtures")
def make_fixtures_cmd(days: int = 45) -> None:
    typer.echo(make_fixtures(days=days))


@app.command("ingest")
def ingest_cmd(raw: bool = typer.Option(True, "--raw/--fixture")) -> None:
    typer.echo(ingest(prefer_raw=raw))


@app.command("train")
def train_cmd(max_origins: int = 40) -> None:
    typer.echo(train_model(max_origins=max_origins))


@app.command("forecast")
def forecast_cmd(origin: Optional[str] = None) -> None:
    bundle = run_forecast(origin=origin)
    typer.echo(
        {
            "origin": str(bundle.origin_utc),
            "rows": len(bundle.rows),
            "score_status": bundle.score_status,
            "contract_status": bundle.contract_status,
            "metrics": bundle.metrics,
        }
    )


@app.command("export-submission")
def export_cmd(origin: Optional[str] = None) -> None:
    typer.echo(export_submission(origin=origin))


@app.command("agent")
def agent_cmd(goal: str = "Audit data then run a 48h forecast and summarize.") -> None:
    trace = run_agent(goal)
    typer.echo({"mode": trace.mode, "final": trace.final_answer, "n_steps": len(trace.steps), "blocked": trace.blocked})


@app.command("serve")
def serve_cmd(host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn

    uvicorn.run("wind_demo.api:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    app()
