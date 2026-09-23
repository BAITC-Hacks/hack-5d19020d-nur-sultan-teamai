import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from .config import data_root, iso, now


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_bytes(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with tmp.open("wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def write_json(path, value):
    atomic_bytes(path, json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False).encode())


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_frame(path, frame):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        frame.to_parquet(tmp, index=False)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


@contextmanager
def db():
    conn = sqlite3.connect(data_root() / "state.sqlite", timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY, key TEXT UNIQUE NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
          state TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          lease_until TEXT, attempts INTEGER NOT NULL DEFAULT 0, result TEXT, error TEXT);
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY, job_id TEXT, ts TEXT, stage TEXT, payload TEXT);
        CREATE TABLE IF NOT EXISTS usage (
          id TEXT PRIMARY KEY, provider TEXT, reserved_usd REAL, actual_usd REAL,
          state TEXT, created_at TEXT, details TEXT);
        CREATE TABLE IF NOT EXISTS downloads (
          key TEXT PRIMARY KEY, bytes INTEGER NOT NULL, created_at TEXT NOT NULL);
    """)
    if "owner" not in {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}:
        conn.execute("ALTER TABLE jobs ADD COLUMN owner TEXT")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def event(job_id, stage, payload):
    with db() as conn:
        conn.execute("INSERT INTO events(job_id,ts,stage,payload) VALUES (?,?,?,?)",
                     (job_id, iso(now()), stage, json.dumps(payload, ensure_ascii=False, default=str)))


def events(job_id=None, limit=200):
    with db() as conn:
        if job_id:
            rows = conn.execute("SELECT * FROM events WHERE job_id=? ORDER BY id DESC LIMIT ?",
                                (job_id, limit)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [{**dict(r), "payload": json.loads(r["payload"])} for r in rows]
