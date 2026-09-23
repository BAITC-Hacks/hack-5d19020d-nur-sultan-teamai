from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .config import get_paths, sites_config
from .storage import ensure_dirs, write_frame
from .weather import power_curve


def make_fixtures(days: int = 45, end: str = "2026-01-31 23:50:00") -> dict:
    """Create synthetic 10-min SCADA CSVs ending before Feb 2026 (no February actuals)."""
    ensure_dirs()
    fixtures = get_paths()["fixtures"]
    end_ts = pd.Timestamp(end)
    start_ts = end_ts - pd.Timedelta(days=days)
    index = pd.date_range(start_ts, end_ts, freq="10min")
    written = []
    for i, site in enumerate(sites_config().sites):
        rng = np.random.default_rng(100 + i)
        # diurnal + noise wind
        hours = index.hour + index.minute / 60
        wind = 7 + 2.5 * np.sin(2 * np.pi * (hours - 6) / 24) + rng.normal(0, 1.2, len(index))
        wind = np.clip(wind, 0.5, 20)
        temp = 2 + 8 * np.sin(2 * np.pi * (index.dayofyear) / 365) + rng.normal(0, 1.0, len(index))
        power = power_curve(wind) * (0.9 + 0.1 * rng.random(len(index)))
        power = np.clip(power, 0, 1)
        frame = pd.DataFrame(
            {
                "source_id": site.turbine_id,
                "timestamp_local": index.strftime("%Y-%m-%d %H:%M:%S"),
                "wind_observed": wind,
                "power": power,
                "temperature_observed": temp,
            }
        )
        path = fixtures / f"scada_{site.turbine_id}.csv"
        write_frame(path, frame)
        written.append(str(path))
    # marker for feb absence
    (fixtures / "README.md").write_text(
        "Synthetic SCADA fixtures. Last timestamp is 2026-01-31 — February 2026 has 0 actual rows by design.\n",
        encoding="utf-8",
    )
    return {"files": written, "rows_each": len(index), "end": end}
