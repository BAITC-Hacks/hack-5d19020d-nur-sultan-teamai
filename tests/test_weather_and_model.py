import json

import numpy as np
import pandas as pd
import pytest

from wind_agent.config import data_root, iso, utc
from wind_agent.evaluation import metrics, monthly_origins
from wind_agent.models import PowerModel
from wind_agent.weather import WeatherUnavailable, _request, parse_index, select_run


def test_release_run_is_before_origin():
    assert iso(select_run("2026-01-31T00:00Z")) == "2026-01-30T12:00:00Z"


def test_index_byte_ranges():
    records = parse_index("1:0:d=2026013012:TMP:2 m above ground:12 hour fcst:\n2:234:d=2026013012:UGRD:100 m above ground:12 hour fcst:\n3:456:d=2026013012:VGRD:100 m above ground:12 hour fcst:")
    assert records[0]["end"] == 233
    assert records[1]["end"] == 455


def test_corrupt_index_rejected():
    with pytest.raises(WeatherUnavailable):
        parse_index("wrong")
    with pytest.raises(WeatherUnavailable):
        parse_index("1:80:d:TMP:2m:fcst:\n2:20:d:UGRD:100m:fcst:")


def test_mvp_has_all_months_and_29_replay_origins():
    dates = monthly_origins()
    validation = [d for d in dates if d.year == 2025]
    replay = [d for d in dates if d >= utc("2026-01-31T00:00Z")]
    assert len(validation) == 48
    assert len({d.month for d in validation}) == 12
    assert len(replay) == 29


@pytest.mark.parametrize("kind", ["train_mean", "wind_bins", "catboost_small", "catboost_pooled"])
def test_model_round_trip_and_bounds(training_data, kind):
    model = PowerModel(kind).fit(training_data, "2025-01-01T00:00Z", with_intervals=kind=="catboost_small")
    result = model.predict(training_data.iloc[:24])
    assert result.prediction.between(0, 1).all()
    version = model.save()
    loaded = PowerModel.load(version)
    np.testing.assert_allclose(result, loaded.predict(training_data.iloc[:24]), equal_nan=True)
    if kind == "catboost_small":
        assert (result.p10 <= result.p50).all()
        assert (result.p50 <= result.p90).all()


def test_model_checksum_blocks_corruption(training_data):
    model = PowerModel("catboost_small").fit(training_data, "2025-01-01T00:00Z")
    version = model.save()
    path = next((data_root()/"models"/version).glob("*.cbm"))
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="checksum"):
        PowerModel.load(version)


def test_model_rejects_future_observations(training_data):
    with pytest.raises(ValueError, match="cutoff"):
        PowerModel().fit(training_data, "2024-01-02T00:00Z")


def test_model_version_path_traversal():
    with pytest.raises(ValueError):
        PowerModel.load("../../secrets")


def test_metrics_and_coverage():
    f = pd.DataFrame({"power":[0.,1.,np.nan], "prediction":[.2,.8,.9]})
    result = metrics(f, expected=4)
    assert result["rmse"] == pytest.approx(.2)
    assert result["bias"] == pytest.approx(0)
    assert result["coverage"] == .5
    assert result["scored_rows"] == 2


def test_empty_metric_not_zero():
    result = metrics(pd.DataFrame({"power":[np.nan], "prediction":[.2]}))
    assert result["rmse"] is None


def test_interval_metrics():
    f = pd.DataFrame({"power":[0.,1.], "prediction":[.1,.9], "p10":[0.,.7], "p50":[.1,.9], "p90":[.3,1.]})
    result = metrics(f)
    assert result["interval_coverage_80"] == 1
    assert result["pinball_p50"] == pytest.approx(.05)


def test_range_request_never_accepts_full_file(monkeypatch):
    import contextlib

    import wind_agent.weather as weather
    class Response:
        status_code = 200
        headers = {}
        def iter_bytes(self):
            pytest.fail("Must reject headers before reading global GRIB")
    class Client:
        @contextlib.contextmanager
        def stream(self, *args, **kwargs):
            yield Response()
    monkeypatch.setattr(weather._LOCAL, "client", Client(), raising=False)
    monkeypatch.setattr(weather.time, "sleep", lambda _: None)
    with pytest.raises(WeatherUnavailable, match="Range request not honored"):
        _request("https://example.invalid/test", (0,99))


def test_card_is_json_no_pickle(training_data):
    model = PowerModel("train_mean").fit(training_data, "2025-01-01T00:00Z")
    version = model.save()
    card = json.loads((data_root()/"models"/version/"card.json").read_text())
    assert card["point_estimator"] == "conditional_mean_squared_error"
    assert card["mode"] == "weather_only_frozen"
