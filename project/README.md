# WIND AGENT

This directory contains the executable implementation described in
`../docs/final/WIND_AGENT_MASTER_FINAL_RU.md`. The current increment establishes the
T00–T02 contracts: an installable package, validated configuration, explicit replay time,
exact hourly forecast intervals, and point-in-time knowledge filtering.

## Quick start

```bash
uv sync --dev
uv run wind-agent --help
uv run wind-agent check-config
uv run pytest
uv run ruff check .
```

The two turbine coordinates and SCADA time semantics are deliberately unresolved. Strict
real-data forecasting must fail until those contracts are confirmed. Provisional and synthetic
development must always be labelled as such.

Large source data, model artifacts, weather caches, secrets, and `.env` files must not be
committed.
