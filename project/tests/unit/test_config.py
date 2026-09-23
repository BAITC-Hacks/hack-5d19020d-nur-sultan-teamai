from pathlib import Path

from wind_agent.config import load_sites


def test_unknown_coordinates_remain_null() -> None:
    config = load_sites(Path("configs/sites.yaml"))
    assert {site.turbine_id for site in config.sites} == {"turbine_1", "turbine_2"}
    assert all(site.latitude is None and site.longitude is None for site in config.sites)
    assert all(site.coordinate_status == "unknown" for site in config.sites)
