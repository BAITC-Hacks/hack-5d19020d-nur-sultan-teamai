import json
from pathlib import Path

import pandas as pd
import streamlit as st

from wind_demo.config import get_paths, load_env
from wind_demo.forecast import run_forecast
from wind_demo.ingest import load_hourly
from wind_demo.storage import ensure_dirs

load_env()
ensure_dirs()

st.set_page_config(page_title="Wind Demo MVP", layout="wide")
st.title("Wind Demo MVP")
st.caption("ML forecast + bounded agent. Synthetic/fixture mode until real XLSX and coordinates are provided.")

origin = st.text_input("Forecast origin UTC (optional ISO)", value="")
col1, col2 = st.columns(2)
with col1:
    if st.button("Run forecast", type="primary"):
        with st.spinner("Forecasting..."):
            bundle = run_forecast(origin=origin or None)
            st.session_state["bundle"] = bundle.model_dump()
with col2:
    if st.button("Show last hourly coverage"):
        hourly = load_hourly()
        st.write(
            {
                "rows": len(hourly),
                "last": str(hourly["valid_start_utc"].max()),
                "feb_2026_rows": int(
                    ((hourly["valid_start_utc"] >= "2026-02-01") & (hourly["valid_start_utc"] < "2026-03-01")).sum()
                ),
            }
        )

bundle = st.session_state.get("bundle")
if bundle:
    st.subheader("Status")
    st.json(
        {
            "origin_utc": bundle["origin_utc"],
            "contract_status": bundle["contract_status"],
            "score_status": bundle["score_status"],
            "metrics": bundle["metrics"],
            "notes": bundle["notes"],
        }
    )
    df = pd.DataFrame(bundle["rows"])
    st.subheader("Forecast")
    st.line_chart(df.pivot_table(index="valid_start_utc", columns="turbine_id", values="power_point_normalized"))
    st.dataframe(df.head(48))

exports = get_paths()["exports"]
files = sorted(exports.glob("forecast_*.json"))
if files:
    st.subheader("Recent exports")
    st.write([p.name for p in files[-5:]])
