# WIND AGENT — Nur Sultan teamAI

Leakage-safe wind-generation forecasting project for the HackAlem AI challenge. The normative
implementation specification is in `docs/final/WIND_AGENT_MASTER_FINAL_RU.md`; runnable code lives
in [`project/`](project/README.md).

```bash
cd project
uv sync --dev
uv run pytest
uv run wind-agent --help
```

Real-data work remains explicitly gated on the original XLSX/PDF inputs and confirmed site/time
contracts. See `project/BLOCKERS.md` and `project/IMPLEMENTATION_STATUS.json` for current status.
