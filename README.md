# hack-5d19020d-nur-sultan-teamai

Hackathon team **Nur_Sultan_teamAI** — agentic AI for wind-turbine power forecasting (HackAlem).

## What is in this repo

| Path | Purpose |
|------|---------|
| [`demo/`](demo/) | **Working MVP** — ingest → weather → CatBoost → 48h forecast → API/UI → LangGraph agent |
| [`docs/final/`](docs/final/) | Full planning package (START_HERE, master spec, review) |
| [`docs/brainstorm/`](docs/brainstorm/) | Earlier GPT/Claude/Gemini notes |
| [`AGENTS.md`](AGENTS.md) | Rules for coding agents (use code-review-graph first) |
| [`.env.example`](.env.example) | Template for API keys (never commit `.env`) |

There is also an experimental root `wind_agent/` package from earlier exploration. For the demo and judging path, use **`demo/`**.

## Quick start (MVP)

```powershell
cd demo
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev]"

# secrets: copy .env.example → .env and set OPENAI_API_KEY
# (or use the repo-root .env — demo loads both)

python scripts\demo_run.py
```

Useful commands after install:

```powershell
wind-demo make-fixtures
wind-demo ingest --fixture
wind-demo train
wind-demo forecast
wind-demo agent
wind-demo serve
streamlit run ui/app.py
```

Tests:

```powershell
pytest -q
```

## Secrets

1. Put **API keys** in `.env` (gitignored), not in chat or Markdown.
2. `OPENAI_API_KEY` — from [platform.openai.com/api-keys](https://platform.openai.com/api-keys).
3. `NVIDIA_API_KEY` — from [build.nvidia.com/settings](https://build.nvidia.com/settings) after redeeming the coupon in the browser. A billing/coupon **URL is not** an API key.
4. ChatGPT / Codex Pro codes activate in the OpenAI account UI — they do not go in `.env`.

Without keys, the demo agent runs in `mock` mode (`WIND_DEMO_LLM_MODE=mock`).

## Real SCADA data

1. Drop the two Excel files into `demo/data/raw/` (names containing `turbine 1` / `turbine 2`).
2. Set `lat` / `lon` in `demo/configs/sites.yaml`.
3. Re-run: `wind-demo ingest` → `train` → `forecast`.

Until then the MVP uses synthetic fixtures (no February 2026 actuals → `score_status=not_evaluated`).

## Docs to read

- Demo runbook: [`demo/README.md`](demo/README.md)
- Assumptions: [`demo/ASSUMPTIONS.md`](demo/ASSUMPTIONS.md)
- Full spec: [`docs/final/WIND_AGENT_MASTER_FINAL_RU.md`](docs/final/WIND_AGENT_MASTER_FINAL_RU.md)
- Start here: [`docs/final/WIND_AGENT_START_HERE_RU.md`](docs/final/WIND_AGENT_START_HERE_RU.md)

## Git

```powershell
git status
git add .
git commit -m "your message"
git push
```

Do **not** `git add .env` or real Excel with private operational data unless the team explicitly agrees.
