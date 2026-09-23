# hack-5d19020d-nur-sultan-teamai

Hackathon team **Nur_Sultan_teamAI** (HackAlem) — agentic AI for **wind-turbine power forecasting**.

**Start here for a working product:** [`demo/`](demo/)

---

## What’s in `demo/` (MVP)

Self-contained package that runs end-to-end without the organizers’ Excel (uses bundled fixtures). Pipeline:

**ingest → weather → CatBoost train → 48h forecast → FastAPI / Streamlit → LangGraph agent**

| Path inside `demo/` | What it is |
|---------------------|------------|
| [`src/wind_demo/`](demo/src/wind_demo/) | Core Python package: ingest, features, weather, train, forecast, storage, schemas |
| [`src/wind_demo/agent/`](demo/src/wind_demo/agent/) | Bounded LangGraph supervisor (tools + OpenAI / NVIDIA / mock) |
| [`src/wind_demo/api.py`](demo/src/wind_demo/api.py) | FastAPI (`/health`, `/forecast`, `/agent/run`) |
| [`src/wind_demo/cli.py`](demo/src/wind_demo/cli.py) | CLI entrypoint `wind-demo …` |
| [`configs/`](demo/configs/) | YAML: sites, time, models, agent policy |
| [`data/fixtures/`](demo/data/fixtures/) | Synthetic SCADA CSVs so the demo works offline |
| [`data/raw/`](demo/data/raw/) | Drop real Excel here (`turbine 1` / `turbine 2` in the filename) |
| [`scripts/demo_run.py`](demo/scripts/demo_run.py) | One-command full smoke run |
| [`ui/app.py`](demo/ui/app.py) | Streamlit UI |
| [`tests/`](demo/tests/) | Pytest smoke tests |
| [`ASSUMPTIONS.md`](demo/ASSUMPTIONS.md) | Explicit demo assumptions (timezone, scoring, fixtures) |
| [`README.md`](demo/README.md) | Detailed demo runbook |

Generated artifacts (`data/processed`, `models`, `traces`, `exports`) and `.env` stay local / gitignored.

Full demo docs: **[`demo/README.md`](demo/README.md)**.

---

## Quick start

```powershell
cd demo
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev]"

# secrets: copy .env.example → .env and set OPENAI_API_KEY
# (repo-root .env also works — packages auto-load both)

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
pytest -q
```

Without API keys, set `WIND_DEMO_LLM_MODE=mock` (agent still runs offline).

---

## Rest of the repo

| Path | Purpose |
|------|---------|
| [`docs/final/`](docs/final/) | Planning package (START_HERE, master spec, review) |
| [`docs/brainstorm/`](docs/brainstorm/) | Earlier GPT / Claude / Gemini notes |
| [`wind_agent/`](wind_agent/) | Experimental root package (GFS / herbie path) — **prefer `demo/` for judging** |
| [`AGENTS.md`](AGENTS.md) | Rules for coding agents |
| [`.env.example`](.env.example) | API key template — **never commit real `.env`** |

## Secrets

1. Put keys only in `.env` or `demo/.env` (gitignored).
2. `OPENAI_API_KEY` — [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
3. `NVIDIA_API_KEY` — real key from [build.nvidia.com/settings](https://build.nvidia.com/settings) (coupon **URLs are not keys**)

## Real SCADA

1. Excel → `demo/data/raw/` (names containing `turbine 1` / `turbine 2`)
2. Set `lat` / `lon` in `demo/configs/sites.yaml`
3. `wind-demo ingest` → `train` → `forecast`

Until then the MVP uses fixtures; February 2026 without actuals → `score_status=not_evaluated`.

## Docs

- Demo runbook: [`demo/README.md`](demo/README.md)
- Assumptions: [`demo/ASSUMPTIONS.md`](demo/ASSUMPTIONS.md)
- Spec: [`docs/final/WIND_AGENT_MASTER_FINAL_RU.md`](docs/final/WIND_AGENT_MASTER_FINAL_RU.md)
- Start here (planning): [`docs/final/WIND_AGENT_START_HERE_RU.md`](docs/final/WIND_AGENT_START_HERE_RU.md)
