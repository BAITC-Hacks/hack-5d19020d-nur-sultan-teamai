import json
import os
import threading
import uuid

import pandas as pd

from .config import data_root, digest, iso, now, project
from .storage import db, event, write_json


def enqueue(kind, payload):
    if kind not in {"forecast", "replay"}:
        raise ValueError("Unknown job kind")
    from .models import active_model
    payload = {**payload, "config_hash": project().fingerprint,
               "model_version": active_model().card["version"]}
    key = digest({"kind": kind, "payload": payload})
    stamp = iso(now())
    with db() as conn:
        conn.execute("INSERT OR IGNORE INTO jobs(id,key,kind,payload,state,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                     (uuid.uuid4().hex, key, kind, json.dumps(payload), "queued", stamp, stamp))
        job = conn.execute("SELECT * FROM jobs WHERE key=?", (key,)).fetchone()
    return decode(job)


def decode(row):
    result = dict(row)
    for field in ["payload", "result"]:
        if result.get(field):
            result[field] = json.loads(result[field])
    result.pop("owner", None)
    return result


def get_job(job_id):
    with db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        raise KeyError(job_id)
    return decode(row)


def list_jobs(limit=50):
    with db() as conn:
        return [decode(r) for r in conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))]


def retry_job(job_id):
    with db() as conn:
        cursor = conn.execute("UPDATE jobs SET state='queued',updated_at=?,attempts=0,error=NULL WHERE id=? AND state='failed'",
                              (iso(now()), job_id))
        if not cursor.rowcount:
            raise ValueError("Only failed jobs can be retried")
    return get_job(job_id)


def claim(owner):
    stamp = iso(now())
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE jobs SET state='failed',error='Worker lease expired after 3 attempts',updated_at=? WHERE state='running' AND lease_until<? AND attempts>=3",
                     (stamp, stamp))
        row = conn.execute("SELECT * FROM jobs WHERE state='queued' OR (state='running' AND lease_until<? AND attempts<3) ORDER BY created_at LIMIT 1", (stamp,)).fetchone()
        if not row:
            return None
        conn.execute("UPDATE jobs SET state='running',owner=?,attempts=attempts+1,lease_until=?,updated_at=? WHERE id=?",
                     (owner, iso(now()+pd.Timedelta(seconds=90)), stamp, row["id"]))
    return decode(row)


def _heartbeat(owner, stop, job_id=None):
    while not stop.is_set():
        write_json(data_root() / "workers" / f"{owner}.json", {"owner": owner, "pid": os.getpid(), "seen_at": iso(now()), "job_id": job_id})
        if job_id:
            with db() as conn:
                conn.execute("UPDATE jobs SET lease_until=?,updated_at=? WHERE id=? AND owner=? AND state='running'",
                             (iso(now()+pd.Timedelta(seconds=90)), iso(now()), job_id, owner))
        stop.wait(20)


def process_one(owner=None):
    from .agent import run_agent
    from .forecast import replay
    owner = owner or uuid.uuid4().hex
    job = claim(owner)
    if not job:
        return False
    stop = threading.Event()
    thread = threading.Thread(target=_heartbeat, args=(owner, stop, job["id"]), daemon=True)
    thread.start()
    event(job["id"], "job_started", {"kind": job["kind"]})
    try:
        payload = job["payload"]
        if payload["config_hash"] != project().fingerprint:
            raise ValueError("Configuration changed after job submission; submit a new job")
        if job["kind"] == "forecast":
            result = run_agent(payload["origin"], job["id"], payload.get("provider", "offline"),
                               strict=payload.get("strict", False), model_version=payload["model_version"])
        else:
            result = replay(payload["start"], payload["end"], payload.get("strict", False),
                            progress=lambda origin, f: event(job["id"], "replay_origin", {"origin": origin, "forecast_id": f}),
                            model_version=payload["model_version"])
        with db() as conn:
            conn.execute("UPDATE jobs SET state='succeeded',result=?,updated_at=?,lease_until=NULL WHERE id=? AND owner=?",
                         (json.dumps(result, default=str), iso(now()), job["id"], owner))
        event(job["id"], "job_succeeded", {"kind": job["kind"]})
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        with db() as conn:
            conn.execute("UPDATE jobs SET state='failed',error=?,updated_at=?,lease_until=NULL WHERE id=? AND owner=?",
                         (error[:1500], iso(now()), job["id"], owner))
        event(job["id"], "job_failed", {"error": error[:1500]})
    finally:
        stop.set()
        thread.join(timeout=5)
    return True


def worker(once=False):
    owner = uuid.uuid4().hex
    idle_stop = threading.Event()
    thread = threading.Thread(target=_heartbeat, args=(owner, idle_stop), daemon=True)
    thread.start()
    try:
        while True:
            handled = process_one(owner)
            if once:
                break
            if not handled:
                idle_stop.wait(2)
    finally:
        idle_stop.set()
        thread.join(timeout=5)
        (data_root() / "workers" / f"{owner}.json").unlink(missing_ok=True)
