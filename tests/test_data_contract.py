import pandas as pd
import pytest

from wind_agent.config import iso, utc
from wind_agent.features import FEATURES, features, training_table
from wind_agent.ingest import hourly_frame


def test_utc_requires_offset():
    with pytest.raises(ValueError, match="explicit UTC offset"):
        utc("2026-01-31")


def test_utc_converts_offsets():
    assert iso("2026-01-31T05:00+05:00") == "2026-01-31T00:00:00Z"


def test_full_hour_mean(raw_hour, cfg):
    frame, report = hourly_frame(raw_hour, cfg, "turbine_1")
    assert frame.iloc[0].power == pytest.approx(.5)
    assert frame.iloc[0].samples == 6
    assert report["full_hours"] == 1
    assert iso(frame.iloc[0].target_time) == "2024-12-31T19:00:00Z"


def test_partial_hour_not_target(raw_hour, cfg):
    frame, report = hourly_frame(raw_hour.iloc[:-1], cfg, "turbine_1")
    assert not frame.eligible.any()
    assert frame.power.isna().all()
    assert report["partial_hours"] == 1


def test_real_zero_is_retained(raw_hour, cfg):
    raw_hour["power"] = 0.
    frame, _ = hourly_frame(raw_hour, cfg, "turbine_1")
    assert frame.iloc[0].power == 0 and frame.iloc[0].eligible


def test_invalid_power_not_clipped(raw_hour, cfg):
    raw_hour.loc[0, "power"] = 1.2
    frame, report = hourly_frame(raw_hour, cfg, "turbine_1")
    assert frame.power.isna().all()
    assert report["invalid_numeric_rows"] == 1


def test_duplicate_intervals_rejected(raw_hour, cfg):
    duplicated = pd.concat([raw_hour, raw_hour.iloc[[0]]], ignore_index=True)
    frame, report = hourly_frame(duplicated, cfg, "turbine_1")
    assert report["duplicate_time_rows"] == 2
    assert not frame.eligible.any()


def test_end_label_moves_interval(raw_hour, cfg):
    cfg = cfg.model_copy(update={"interval_label": "end"})
    raw_hour["time"] += pd.Timedelta(minutes=10)
    frame, _ = hourly_frame(raw_hour, cfg, "turbine_1")
    assert frame.iloc[0].eligible
    assert iso(frame.iloc[0].target_time) == "2024-12-31T19:00:00Z"


def test_ambiguous_timezone_not_inferred(raw_hour, cfg):
    ambiguous = raw_hour.copy()
    ambiguous["time"] = pd.date_range("2024-02-29T23:00", periods=6, freq="10min")
    combined = pd.concat([raw_hour, ambiguous], ignore_index=True)
    _, report = hourly_frame(combined, cfg, "turbine_1")
    assert report["invalid_or_ambiguous_time_rows"] == 6


def test_availability_after_hour_end(raw_hour, cfg):
    frame, _ = hourly_frame(raw_hour, cfg, "turbine_1")
    assert frame.iloc[0].obs_available_at - frame.iloc[0].target_time == pd.Timedelta(minutes=70)


def test_missing_hour_is_not_zero(raw_hour, cfg):
    later = raw_hour.copy()
    later["time"] += pd.Timedelta(hours=2)
    frame, report = hourly_frame(pd.concat([raw_hour, later]), cfg, "turbine_1")
    assert len(frame) == 3 and report["empty_hours"] == 1
    assert pd.isna(frame.iloc[1].power)


def test_feature_matrix_has_no_telemetry(training_data):
    matrix = features(training_data)
    altered = training_data.assign(power=999, wind_observed=999, temperature_observed=999)
    pd.testing.assert_frame_equal(matrix, features(altered))
    assert list(matrix) == FEATURES


def test_future_labels_excluded(training_data):
    weather = training_data.drop(columns=["power", "obs_available_at", "sample_weight"])
    obs = training_data[["site_id", "target_time", "power", "obs_available_at"]].assign(eligible=True)
    cutoff = "2024-01-05T00:00:00Z"
    table = training_table(weather, obs, cutoff)
    assert (table.obs_available_at <= utc(cutoff)).all()
    assert (table.target_time < utc(cutoff)).all()


def test_future_weather_rejected(training_data):
    weather = training_data.drop(columns=["power", "obs_available_at", "sample_weight"])
    weather["weather_available_at"] = weather.origin+pd.Timedelta(hours=1)
    obs = training_data[["site_id", "target_time", "power", "obs_available_at"]].assign(eligible=True)
    with pytest.raises(ValueError, match="leakage"):
        training_table(weather, obs, "2025-01-01T00:00Z")


def test_config_change_changes_fingerprint(cfg):
    changed = cfg.model_copy(update={"timezone": "UTC"})
    assert changed.fingerprint != cfg.fingerprint
