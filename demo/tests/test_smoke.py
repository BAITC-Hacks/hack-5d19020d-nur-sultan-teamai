from __future__ import annotations

import pandas as pd

from wind_demo.fixtures import make_fixtures
from wind_demo.forecast import run_forecast
from wind_demo.ingest import ingest, load_hourly
from wind_demo.train import train_model
from wind_demo.weather import FixtureProvider, power_curve
from wind_demo.config import sites_config, time_config


def test_power_curve_bounds():
    import numpy as np

    y = power_curve(np.array([0.0, 3.0, 8.0, 12.0, 30.0]))
    assert y[0] == 0
    assert 0 < y[2] < 1
    assert y[3] == 1
    assert y[4] == 0


def test_fixture_ingest_no_february():
    make_fixtures(days=40)
    audit = ingest(prefer_raw=False)
    assert audit["mode"] == "fixture"
    hourly = load_hourly()
    feb = hourly[(hourly["valid_start_utc"] >= "2026-02-01") & (hourly["valid_start_utc"] < "2026-03-01")]
    assert len(feb) == 0
    assert hourly["valid_start_utc"].max() < pd.Timestamp("2026-02-01", tz="UTC")


def test_train_and_forecast_smoke():
    make_fixtures(days=40)
    ingest(prefer_raw=False)
    metrics = train_model(max_origins=20)
    assert "rmse" in metrics
    bundle = run_forecast()
    assert len(bundle.rows) == len(sites_config().sites) * time_config().horizon_hours
    assert bundle.score_status in {"ok", "not_evaluated"}


def test_fixture_weather_horizon():
    snap = FixtureProvider().fetch(
        pd.Timestamp("2026-01-31", tz="UTC").to_pydatetime(),
        sites_config().sites,
        time_config().horizon_hours,
    )
    assert snap.contract_status == "synthetic"
    assert len(snap.points) == len(sites_config().sites) * time_config().horizon_hours
