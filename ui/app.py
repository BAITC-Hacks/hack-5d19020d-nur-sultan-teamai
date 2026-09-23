"""Operational forecast reading surface; see PRODUCT.md for delegated choices."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from wind_agent.api import local_token
from wind_agent.config import data_root, project
from wind_agent.storage import read_json

st.set_page_config(page_title="WIND AGENT · Прогноз мощности", layout="wide")
st.markdown("""
<!-- THESIS: A calibrated forecast strip makes origin, horizon and uncertainty readable together.
OWN-WORLD: white instrument sheet, blue scale, dark ink, thin rules; functional measurement typography.
STORY: select a dated release, inspect 48 hours, verify evidence, export the original release.
FIRST VIEWPORT: compact title, release controls, wide calibrated plot, source and time evidence below.
FORM: hydrological gauge strip translated into a power time scale, grounded candidate 5, seed 0fd41e49.
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, and DESIGN.md
-->
<style>
.block-container {padding-top:2rem; padding-bottom:3rem; max-width:1450px;}
h1 {font-size:2.2rem !important; font-weight:650 !important; letter-spacing:-.025em;}
h2 {margin-top:1.4rem; font-size:1.4rem !important;}
section[data-testid="stSidebar"] {border-right:1px solid #c4d7e1;}
div[data-testid="stDataFrame"] {font-variant-numeric:tabular-nums;}
button:focus-visible, input:focus-visible {outline:3px solid #176083; outline-offset:3px;}
::selection {background:#a9d8e9; color:#16344b;}
a {text-underline-offset:.2em;}
@media(max-width:700px){.block-container{padding:1rem;} h1{font-size:1.8rem !important;}}
</style>
""", unsafe_allow_html=True)

API = "http://127.0.0.1:8000"


def get(path, default=None):
    try:
        response = httpx.get(API+path, timeout=8)
        if response.status_code in (200, 503):
            return response.json()
    except httpx.HTTPError:
        pass
    return default


def submit(path, body):
    try:
        response = httpx.post(API+path, json=body, headers={"Authorization": "Bearer "+local_token()}, timeout=10)
        if response.status_code >= 400:
            st.error(response.json().get("detail", "Не удалось создать задачу"))
            return
        job = response.json()
        st.session_state["job_id"] = job["id"]
        st.success("Задача в очереди. Её состояние появится в разделе «Агент и задачи».")
    except (httpx.HTTPError, ValueError):
        st.error("API недоступен. Запустите scripts/start.ps1 и обновите страницу.")


st.title("WIND AGENT")
st.caption("Почасовой прогноз нормализованной мощности · две турбины · горизонт 48 часов")
health = get("/health")
if health is None:
    st.warning("Сервис ещё не запущен. Выполните scripts/start.ps1 из папки проекта.")
    if st.button("Проверить подключение"):
        st.rerun()
    st.stop()

cfg = project()
readiness = get("/ready", {})
with st.sidebar:
    st.subheader("Новый расчёт")
    st.caption("Каждый выпуск сохраняет свой момент прогноза и версию модели.")
    selected_day = st.date_input("Дата выпуска, UTC", date(2026, 2, 1), min_value=date(2026, 1, 31), max_value=date.today())
    provider_label = st.selectbox("Диспетчер", ["Локальный · без API", "NVIDIA", "OpenAI"])
    provider = {"Локальный · без API": "offline", "NVIDIA": "nvidia", "OpenAI": "openai"}[provider_label]
    if st.button("Рассчитать 48 часов", type="primary", use_container_width=True, disabled=not readiness.get("ready", False)):
        submit("/forecast-jobs", {"origin": selected_day.isoformat()+"T00:00:00Z", "provider": provider})
    if not readiness.get("ready"):
        missing = [k for k, v in readiness.get("checks", {}).items() if not v]
        st.warning("Ожидается: " + ", ".join(missing))
    st.divider()
    st.caption("Источник: NOAA GFS\n\nЧисленный прогноз: обученная модель CPU\n\nОблачный агент: только выбор разрешённых действий")
    if st.button("Обновить экран", use_container_width=True):
        st.rerun()
    st.caption("Все часы на экране — UTC. Мощность в долях от нормировки исходных данных.")

if not cfg.time_metadata_confirmed:
    st.info("Тестовый временной контракт: Excel — Asia/Almaty, метка — начало интервала. Подтверждение организаторов ожидается.")

forecast_tab, validation_tab, quality_tab, agent_tab = st.tabs(["Прогноз", "Проверка точности", "Данные и допущения", "Агент и задачи"])

with forecast_tab:
    releases = get("/forecasts", [])
    if not releases:
        st.warning("Пока нет сохранённых прогнозов. После подготовки модели запустите расчёт слева.")
    else:
        a, b = st.columns([2, 1])
        with a:
            release = st.selectbox("Сохранённый выпуск", releases,
                                   format_func=lambda r: pd.Timestamp(r["origin"]).strftime("%d.%m.%Y %H:%M UTC")+" · "+r["model_kind"])
        with b:
            site = st.selectbox("Турбина", cfg.sites, format_func=lambda s: s.label)
        content = get("/forecasts/"+release["forecast_id"])
        if content:
            frame = pd.DataFrame(content["rows"])
            frame["target_time"] = pd.to_datetime(frame.target_time, utc=True)
            subset = frame[frame.site_id == site.site_id].sort_values("target_time")
            fig = go.Figure()
            if subset.p10.notna().all():
                fig.add_trace(go.Scatter(x=subset.target_time, y=subset.p90, line={"width":0}, showlegend=False, hoverinfo="skip"))
                fig.add_trace(go.Scatter(x=subset.target_time, y=subset.p10, line={"width":0}, fill="tonexty",
                                         fillcolor="rgba(23,96,131,.16)", name="Квантили 10–90%", hoverinfo="skip"))
            fig.add_trace(go.Scatter(x=subset.target_time, y=subset.prediction, mode="lines",
                                     line={"color":"#176083", "width":3}, name="Прогноз",
                                     hovertemplate="%{x|%d.%m %H:%M UTC}<br>Мощность: %{y:.3f}<extra></extra>"))
            obs_path = data_root()/"observations"/cfg.fingerprint/"hourly.parquet"
            if obs_path.exists():
                observed = pd.read_parquet(obs_path)
                actual = observed[(observed.site_id == site.site_id) & observed.eligible &
                                  observed.target_time.isin(subset.target_time)]
                if not actual.empty:
                    fig.add_trace(go.Scatter(x=actual.target_time, y=actual.power, name="Факт из Excel",
                                             line={"color":"#9a4f13", "width":2, "dash":"dot"}))
            fig.update_layout(height=410, margin={"l":5,"r":10,"t":20,"b":5}, paper_bgcolor="#f7fafc",
                              plot_bgcolor="#f7fafc", font={"family":"Segoe UI, sans-serif", "color":"#16344b"},
                              hovermode="x unified", legend={"orientation":"h", "y":1.12},
                              xaxis={"title":"Начало прогнозируемого часа · UTC", "gridcolor":"#dce6ed"},
                              yaxis={"title":"Нормализованная мощность", "range":[0,1], "dtick":.2, "gridcolor":"#cadbe5"})
            st.plotly_chart(fig, use_container_width=True, config={"displaylogo":False})
            st.caption(f"Выпуск погоды: {release['weather_run']} · GFS {release['grid']} · обучение до {release['fit_cutoff']}")
            if subset.p10.notna().all():
                st.caption("Затенение — предсказанные квантили, не гарантия 80% покрытия. Измеренное покрытие — во вкладке точности.")
            else:
                st.caption("Для выбранной простой модели интервал неопределённости не оценивался.")
            csv_path = data_root()/"forecasts"/release["forecast_id"]/"forecast.csv"
            st.download_button("Скачать выпуск CSV · обе турбины", csv_path.read_bytes(), file_name=release["forecast_id"]+".csv", mime="text/csv")
            with st.expander("Почасовые значения и источник"):
                st.dataframe(subset[["target_time", "prediction", "p10", "p50", "p90", "wind100", "temperature_2m"]], hide_index=True, use_container_width=True)
                st.json(content["manifest"])
    replay_path = data_root()/"replays"/"latest.json"
    if replay_path.exists():
        replay = read_json(replay_path)
        st.subheader("Февральское воспроизведение")
        st.write(f"{replay['origins']} ежедневных выпусков · {replay['rows']} строк · модель зафиксирована на весь период.")
        st.caption("Фактическая мощность за февраль не предоставлена. Точность на этом месяце пока неизвестна.")
        p = data_root()/"replays"/replay["id"]/"february_origins.csv"
        st.download_button("Скачать февраль · все выпуски", p.read_bytes(), "february_origins.csv", "text/csv")

with validation_tab:
    scores = get("/metrics", {})
    if not scores.get("available"):
        st.info("Валидация ещё не выполнена. Результаты появятся после wind-agent validate.")
    else:
        report = scores["validation"]
        st.subheader("Модель выбирается на 2025 году")
        st.write("Каждый месяц начинается с новой границы обучения. Внутри месяца фактическая мощность не обновляет модель.")
        st.caption("Меньше RMSE и MAE — лучше. Все модели сравниваются на одинаковых доступных часах; турбины и месяцы имеют равный вес.")
        st.dataframe(pd.DataFrame(report["summaries"]).sort_values("macro_rmse"), hide_index=True, use_container_width=True)
        st.write("Выбрана модель: **"+report["selected_model"]+"**")
        if scores.get("holdout"):
            st.subheader("Независимая проверка · январь 2026")
            hold = scores["holdout"]
            st.caption(f"{hold['origins']} выпусков. Этот месяц не использовался для выбора модели.")
            st.dataframe(pd.DataFrame(hold["sites"]).T, use_container_width=True)
        with st.expander("Покрытие и метрики по месяцам"):
            st.dataframe(pd.DataFrame(report["folds"]), hide_index=True, use_container_width=True)

with quality_tab:
    st.subheader("Что известно о данных")
    audit = get("/audit", {})
    if audit:
        st.dataframe(pd.DataFrame(audit["sites"])[["site_id", "input_rows", "full_hours", "partial_hours", "empty_hours", "invalid_or_ambiguous_time_rows"]], hide_index=True, use_container_width=True)
    st.write("В обучение входят только часы с шестью корректными 10-минутными измерениями. Пропуски не заменяются нулями.")
    st.write("Координаты взяты из ссылок официального задания. Ветер GFS на 100 м — погодный признак; высота ступицы турбин неизвестна.")
    st.write("Публикация погоды: проверяются метки S3 Last-Modified, дополнительно принят запас 8 часов после старта модели. Эта политика ещё не подтверждена организаторами.")
    st.write("Разрешение 1° выбрано для экономного MVP. Оно не описывает местный рельеф с точностью площадки.")
    st.warning("Строгая сдача закрыта до подтверждения временного контракта. Выгрузки MVP помечены provisional.")
    with st.expander("Текущая конфигурация"):
        st.json(cfg.model_dump())

with agent_tab:
    st.subheader("Очередь и решения")
    jobs = get("/jobs", [])
    if jobs:
        st.dataframe(pd.DataFrame(jobs)[["id", "kind", "state", "created_at", "attempts", "error"]], hide_index=True, use_container_width=True)
        job_id = st.selectbox("Журнал задачи", [j["id"] for j in jobs])
        chosen_job = next(j for j in jobs if j["id"] == job_id)
        if chosen_job["state"] == "failed" and st.button("Повторить неудачную задачу"):
            submit("/jobs/"+job_id+"/retry", {})
        traces = get("/traces?job_id="+job_id, [])
    else:
        st.caption("Очередь пуста. Запустите расчёт в левой панели.")
        traces = get("/traces", [])
    for trace in reversed(traces):
        with st.expander(trace["stage"]+" · "+trace["ts"]):
            st.json(trace["payload"])
    st.caption("LLM может запросить аудит, прочитать карточку модели, запустить проверенный расчёт и завершить задачу. Менять значения прогноза он не может.")
    with st.expander("Учёт API-запросов"):
        st.json(get("/usage", {}))
