import numpy as np
import pandas as pd
import pytest

from wind_agent.config import project


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("WIND_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("WIND_API_TOKEN", "unit-test-only-token")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)


@pytest.fixture
def cfg():
    return project()


@pytest.fixture
def raw_hour():
    return pd.DataFrame({"id": range(6), "time": pd.date_range("2025-01-01", periods=6, freq="10min"),
                         "wind": [3.] * 6, "power": [0., .2, .4, .6, .8, 1.], "temp": [-5.] * 6})


@pytest.fixture
def training_data(cfg):
    rng = np.random.default_rng(42)
    rows = []
    for site in cfg.sites:
        for i, target in enumerate(pd.date_range("2024-01-01", periods=400, freq="h", tz="UTC")):
            wind = float(rng.uniform(0, 15))
            rows.append({"site_id": site.site_id, "target_time": target, "origin": target.floor("D"),
                         "wind100": wind, "u100": wind*.8, "v100": wind*.6, "temperature_2m": 5.,
                         "nwp_lead_hours": 12+i % 24, "lead_hours": i % 24,
                         "weather_available_at": target.floor("D")-pd.Timedelta(hours=4),
                         "obs_available_at": target+pd.Timedelta(hours=1, minutes=10),
                         "power": min(1., (wind/15)**2), "sample_weight": 1., "config_hash": cfg.fingerprint})
    return pd.DataFrame(rows)
