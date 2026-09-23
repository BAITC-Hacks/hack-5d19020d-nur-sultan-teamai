"""Command-line entry point."""

import json
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from wind_agent import __version__
from wind_agent.clock import hourly_intervals
from wind_agent.config import load_sites

app = typer.Typer(no_args_is_help=True, help="Leakage-safe WIND AGENT tooling.")


@app.command()
def version() -> None:
    """Print the package version."""

    typer.echo(__version__)


@app.command("check-config")
def check_config(
    sites: Annotated[Path, typer.Option(exists=True, readable=True)] = Path("configs/sites.yaml"),
) -> None:
    """Validate site configuration without promoting unknowns."""

    config = load_sites(sites)
    unresolved = [site.turbine_id for site in config.sites if site.coordinate_status != "confirmed"]
    typer.echo(json.dumps({"valid": True, "unresolved_coordinates": unresolved}))


@app.command("show-intervals")
def show_intervals(
    origin: Annotated[datetime, typer.Option(help="Timezone-aware UTC forecast origin")],
    horizon: Annotated[int, typer.Option(min=1, max=240)] = 48,
) -> None:
    """Print the exact interval contract for a forecast batch."""

    rows = [interval.model_dump(mode="json") for interval in hourly_intervals(origin, horizon)]
    typer.echo(json.dumps(rows, indent=2))
