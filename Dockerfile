FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY wind_agent ./wind_agent
COPY config ./config
COPY ui ./ui
COPY .streamlit ./.streamlit
RUN pip install --no-cache-dir uv==0.12.18 && uv sync --frozen --no-dev --no-editable
ENV PATH="/app/.venv/bin:$PATH" WIND_DATA_DIR=/data WIND_RAW_DIR=/inputs
CMD ["uvicorn", "wind_agent.api:app", "--host", "0.0.0.0", "--port", "8000"]
