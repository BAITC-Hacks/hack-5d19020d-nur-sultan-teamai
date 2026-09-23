"""Subset genuine archived GFS forecast runs. Never use reanalysis or stitched weather."""
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.utils import parsedate_to_datetime

import httpx
import numpy as np
import pandas as pd

from .config import data_root, digest, iso, now, project, utc
from .storage import atomic_bytes, db, read_json, sha256, write_frame, write_json

SOURCE = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"
MAX_TOTAL_BYTES = 20 * 1024**3
FIELDS = [("TMP", "2 m above ground"), ("UGRD", "100 m above ground"), ("VGRD", "100 m above ground")]
WEATHER_SCHEMA = "gfs-bilinear-1h-mean-uv-t2-v1"
_LOCAL = threading.local()
_ECCODES_LOCK = threading.Lock()


class WeatherUnavailable(RuntimeError):
    pass


def select_run(origin, lag=8):
    return (utc(origin) - pd.Timedelta(hours=lag)).floor("6h")


def parse_index(text):
    records = []
    for line in text.strip().splitlines():
        parts = line.split(":")
        if len(parts) < 6:
            raise WeatherUnavailable("Malformed GRIB index")
        records.append({"offset": int(parts[1]), "variable": parts[3], "level": parts[4], "step": parts[5]})
    for a, b in zip(records, records[1:]):
        if b["offset"] <= a["offset"]:
            raise WeatherUnavailable("Unordered GRIB byte offsets")
        a["end"] = b["offset"] - 1
    return records


def _request(url, byte_range=None):
    if not hasattr(_LOCAL, "client"):
        _LOCAL.client = httpx.Client(timeout=35, follow_redirects=False)
    headers = {"Range": f"bytes={byte_range[0]}-{byte_range[1]}"} if byte_range else {}
    expected = byte_range[1] - byte_range[0] + 1 if byte_range else 200_000
    key = digest([url, byte_range])
    # Reserve transfer bytes before a request; reservations survive uncertain failures.
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        used = conn.execute("SELECT COALESCE(SUM(bytes),0) FROM downloads").fetchone()[0]
        if used + 3 * expected > MAX_TOTAL_BYTES:
            raise WeatherUnavailable("Weather transfer cap reached (20 GiB); inspect state.sqlite")
        conn.execute("INSERT INTO downloads(key,bytes,created_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET bytes=bytes+excluded.bytes",
                     (key, 3 * expected, iso(now())))
    error = None
    for attempt in range(3):
        try:
            with _LOCAL.client.stream("GET", url, headers=headers) as response:
                if byte_range:
                    prefix = f"bytes {byte_range[0]}-{byte_range[1]}/"
                    if response.status_code != 206 or not response.headers.get("Content-Range", "").startswith(prefix):
                        raise WeatherUnavailable(f"Range request not honored: HTTP {response.status_code}")
                else:
                    response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > expected:
                        raise WeatherUnavailable("Response exceeds planned transfer size")
                if byte_range and len(content) != expected:
                    raise WeatherUnavailable("Incomplete GRIB byte range")
                meta = {"url": url, "range": byte_range, "retrieved_at": iso(now()),
                        "last_modified": response.headers.get("last-modified"),
                        "etag": response.headers.get("etag"), "bytes": len(content)}
                with db() as conn:
                    # Conservatively retain failed-attempt reservations; release unused retries.
                    release = (2 - attempt) * expected + (expected - len(content))
                    conn.execute("UPDATE downloads SET bytes=MAX(0,bytes-?) WHERE key=?", (release, key))
                return bytes(content), meta
        except (httpx.HTTPError, WeatherUnavailable) as exc:
            error = exc
            if attempt < 2:
                time.sleep(1 + 2**attempt)
    raise WeatherUnavailable(f"GFS request failed: {type(error).__name__}: {error}")


def _message_points(payload, sites, run, lead, field):
    # The Windows ecCodes definitions parser is not safe during concurrent initialization.
    with _ECCODES_LOCK:
        return _decode_points(payload, sites, run, lead, field)


def _decode_points(payload, sites, run, lead, field):
    from eccodes import codes_get, codes_get_array, codes_new_from_message, codes_release
    handle = codes_new_from_message(payload)
    try:
        if codes_get(handle, "stepType") != "instant":
            raise WeatherUnavailable("Expected instantaneous wind/temperature GRIB field")
        actual_run = pd.to_datetime(str(codes_get(handle, "dataDate")) + f'{codes_get(handle, "dataTime"):04d}',
                                    format="%Y%m%d%H%M", utc=True)
        if actual_run != run or int(codes_get(handle, "endStep")) != lead:
            raise WeatherUnavailable("GRIB run/forecast step does not match its URL")
        expected_parameter = {"TMP": {"2t", "t2m", "t"}, "UGRD": {"100u", "u100", "u"}, "VGRD": {"100v", "v100", "v"}}[field[0]]
        short = codes_get(handle, "shortName")
        if short not in expected_parameter:
            raise WeatherUnavailable(f"Unexpected GRIB parameter {short}")
        if codes_get(handle, "typeOfLevel") != "heightAboveGround" or int(codes_get(handle, "level")) != (2 if field[0] == "TMP" else 100):
            raise WeatherUnavailable("Unexpected GRIB field height")
        unit = codes_get(handle, "units")
        if unit not in ({"K"} if field[0] == "TMP" else {"m s**-1", "m s-1"}):
            raise WeatherUnavailable(f"Unexpected units {unit}")
        ni, nj = int(codes_get(handle, "Ni")), int(codes_get(handle, "Nj"))
        lat = np.asarray(codes_get_array(handle, "latitudes")).reshape(nj, ni)
        lon = np.asarray(codes_get_array(handle, "longitudes")).reshape(nj, ni)
        values = np.asarray(codes_get_array(handle, "values")).reshape(nj, ni)
        points = {}
        for site in sites:
            # GFS regular lat/lon grid, two bracketing coordinates per axis.
            ys = np.argsort(np.abs(lat[:, 0] - site.latitude))[:2]
            xs = np.argsort(np.abs(lon[0] - (site.longitude % 360)))[:2]
            y0, y1 = sorted(ys, key=lambda y: lat[y, 0])
            x0, x1 = sorted(xs, key=lambda x: lon[0, x])
            fy = (site.latitude - lat[y0, 0]) / (lat[y1, 0] - lat[y0, 0])
            fx = ((site.longitude % 360) - lon[0, x0]) / (lon[0, x1] - lon[0, x0])
            if not (-1e-8 <= fx <= 1.00000001 and -1e-8 <= fy <= 1.00000001):
                raise WeatherUnavailable("Coordinates not bracketed by selected GFS grid cells")
            value = ((1-fx)*(1-fy)*values[y0, x0] + fx*(1-fy)*values[y0, x1]
                     + (1-fx)*fy*values[y1, x0] + fx*fy*values[y1, x1])
            if not np.isfinite(value) or abs(value) > 1e6:
                raise WeatherUnavailable("Missing GRIB grid value")
            points[site.site_id] = float(value - 273.15 if field[0] == "TMP" else value)
        return points
    finally:
        codes_release(handle)


def _step(run, lead, cfg):
    filename = f"gfs.t{run:%H}z.pgrb2.{cfg.gfs_grid}.f{lead:03d}"
    url = f"{SOURCE}/gfs.{run:%Y%m%d}/{run:%H}/atmos/{filename}"
    root = data_root() / "weather_raw" / f"{run:%Y%m%d%H}" / cfg.gfs_grid
    index_path = root / f"{filename}.idx"
    if not index_path.exists():
        content, meta = _request(url + ".idx")
        atomic_bytes(index_path, content)
        write_json(index_path.with_suffix(".index.json"), meta)
    records = parse_index(index_path.read_text())
    result, evidence = {}, []
    for field in FIELDS:
        matches = [r for r in records if (r["variable"], r["level"]) == field and "end" in r]
        if len(matches) != 1:
            raise WeatherUnavailable(f"Missing/ambiguous GFS field {field}")
        item = matches[0]
        path = root / f"{filename}.{field[0]}.grib2"
        meta_path = path.with_suffix(".json")
        if path.exists() and meta_path.exists():
            meta = read_json(meta_path)
            if sha256(path) != meta["sha256"]:
                raise WeatherUnavailable("Cached GRIB checksum mismatch; inspect cache")
            payload = path.read_bytes()
        else:
            payload, meta = _request(url, (item["offset"], item["end"]))
            atomic_bytes(path, payload)
            meta.update(sha256=sha256(path), variable=field[0], level=field[1])
            write_json(meta_path, meta)
        result[field[0]] = _message_points(payload, cfg.sites, run, lead, field)
        evidence.append(meta)
    return {"lead": lead, "values": result, "evidence": evidence}


def weather_path(origin, cfg=None):
    cfg = cfg or project()
    return data_root() / "weather" / cfg.fingerprint / f"{utc(origin):%Y%m%dT%H%M%SZ}.parquet"


def fetch_weather(origin, force=False):
    cfg = project()
    origin = utc(origin)
    if origin != origin.floor("h"):
        raise ValueError("Forecast origin must be an exact hour")
    path = weather_path(origin, cfg)
    manifest_path = path.with_suffix(".json")
    if path.exists() and manifest_path.exists() and not force:
        manifest = read_json(manifest_path)
        if manifest.get("sha256") == sha256(path):
            return pd.read_parquet(path), manifest
        raise WeatherUnavailable("Weather snapshot checksum mismatch")
    run = select_run(origin, cfg.weather_release_lag_hours)
    first = int((origin-run).total_seconds()/3600)
    leads = list(range(first // 3 * 3, math.ceil((first+cfg.forecast_hours)/3)*3 + 1, 3))
    steps = [_step(run, lead, cfg) for lead in leads]
    headers = [m for s in steps for m in s["evidence"]]
    modified = [pd.Timestamp(parsedate_to_datetime(m["last_modified"])) for m in headers if m["last_modified"]]
    assumed_available = run + pd.Timedelta(hours=cfg.weather_release_lag_hours)
    available = max([assumed_available, *modified])
    if available > origin:
        raise WeatherUnavailable(f"Weather files were not evidenced available by origin: {iso(available)} > {iso(origin)}")
    rows = []
    for site in cfg.sites:
        points = np.arange(first, first+cfg.forecast_hours+1)
        vals = {v: np.interp(points, leads, [s["values"][v][site.site_id] for s in steps]) for v in ["TMP", "UGRD", "VGRD"]}
        means = {k: (a[:-1] + a[1:])/2 for k, a in vals.items()}
        for h in range(cfg.forecast_hours):
            u, v = means["UGRD"][h], means["VGRD"][h]
            rows.append({"site_id": site.site_id, "origin": origin, "target_time": origin+pd.Timedelta(hours=h),
                         "u100": u, "v100": v, "temperature_2m": means["TMP"][h],
                         "wind100": float(np.hypot(u, v)), "run_init": run,
                         "weather_available_at": available, "lead_hours": h,
                         "nwp_lead_hours": first+h, "config_hash": cfg.fingerprint})
    frame = pd.DataFrame(rows)
    write_frame(path, frame)
    manifest = {"schema": WEATHER_SCHEMA, "config_hash": cfg.fingerprint, "origin": iso(origin),
                "run_init": iso(run), "available_at": iso(available), "retrieved_at": iso(now()),
                "availability_evidence": "S3 Last-Modified plus conservative configured release lag",
                "release_lag_assumed": not cfg.weather_release_lag_confirmed,
                "grid": cfg.gfs_grid, "spatial_method": "bilinear on regular lat/lon grid",
                "temporal_method": "3h forecast u/v/T linear interpolation, mean of hourly endpoints",
                "wind_height_m": 100, "hub_height_known": False, "rows": len(frame),
                "sha256": sha256(path), "objects": headers}
    write_json(manifest_path, manifest)
    return frame, manifest


def fetch_many(origins, progress=None):
    origins = sorted(set(utc(o) for o in origins))
    summary = {"requested": len(origins), "ok": [], "failed": []}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(fetch_weather, o): o for o in origins}
        for future in as_completed(futures):
            origin = futures[future]
            try:
                frame, manifest = future.result()
                summary["ok"].append(iso(origin))
                status = "ok"
            except Exception as exc:
                summary["failed"].append({"origin": iso(origin), "error": f"{type(exc).__name__}: {exc}"})
                status = "failed"
            if progress:
                progress(origin, status, len(summary["ok"])+len(summary["failed"]), len(origins))
    write_json(data_root() / "reports" / "weather_fetch.json", summary)
    return summary


def cached_weather(before=None):
    paths = sorted((data_root() / "weather" / project().fingerprint).glob("*.parquet"))
    frames = []
    for path in paths:
        if before and utc(path.stem.replace("T", " ").replace("Z", "+00:00")) >= utc(before):
            continue
        manifest = read_json(path.with_suffix(".json"))
        if manifest["config_hash"] != project().fingerprint or sha256(path) != manifest["sha256"]:
            raise WeatherUnavailable("Cached weather contract/checksum mismatch")
        frames.append(pd.read_parquet(path))
    if not frames:
        raise WeatherUnavailable("No cached forecast weather. Run wind-agent weather first")
    return pd.concat(frames, ignore_index=True)
