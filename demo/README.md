# Wind Demo MVP

Self-contained working demo for the agentic wind-power forecast challenge.

## What it does

1. Ingest SCADA (real XLSX in `data/raw/` **or** bundled fixtures)
2. Build hourly normalized power
3. Fetch weather (Open-Meteo if lat/lon set, else synthetic fixture weather)
4. Train CatBoost and run **48h** forecasts
5. Score only when actuals exist; February 2026 with no actuals → `not_evaluated`
6. FastAPI + Streamlit UI + LangGraph agent (OpenAI / NVIDIA / **mock** offline)

## Setup

```powershell
cd demo
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev]"
```

### Secrets

Create `demo/.env` (gitignored) or use the repo-root `.env`:

```env
OPENAI_API_KEY=sk-proj-...
NVIDIA_API_KEY=
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
WIND_DEMO_LLM_MODE=openai
```

- Demo loads `demo/.env` first, then parent `../.env`.
- NVIDIA coupon/billing **links are not keys** — redeem in the browser, then paste the real API key.
- No key → set `WIND_DEMO_LLM_MODE=mock`.

## Run

One-shot:

```powershell
python scripts\demo_run.py
```

Step by step:

```powershell
wind-demo make-fixtures
wind-demo ingest --fixture
wind-demo train
wind-demo forecast
wind-demo agent
```

API:

```powershell
wind-demo serve
# GET  http://127.0.0.1:8000/health
# POST http://127.0.0.1:8000/forecast
# POST http://127.0.0.1:8000/agent/run
```

UI:

```powershell
streamlit run ui/app.py
```

Tests:

```powershell
pytest -q
```

## Real data

1. Drop Excel into `data/raw/` (filenames containing `turbine 1` / `turbine 2`)
2. Set `lat` / `lon` in `configs/sites.yaml`
3. Re-run ingest → train → forecast

See also [`ASSUMPTIONS.md`](ASSUMPTIONS.md).
