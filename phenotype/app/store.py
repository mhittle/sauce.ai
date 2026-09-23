"""SQLite persistence (stdlib): jobs and the literature HTTP cache."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL,
    status TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT '',
    progress_json TEXT,
    spec_json TEXT NOT NULL,
    result_json TEXT,
    report_html TEXT,
    error TEXT,
    emailed_at REAL
);
CREATE TABLE IF NOT EXISTS http_cache (
    key TEXT PRIMARY KEY,
    fetched_at REAL NOT NULL,
    body TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: str) -> None:
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        if path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)

    def _x(self, sql: str, args: tuple = ()):
        with self._lock:
            return self._conn.execute(sql, args)

    # -- jobs -------------------------------------------------------------------
    def create_job(self, email: str, spec: dict) -> str:
        job_id = uuid.uuid4().hex[:16]
        self._x("INSERT INTO jobs(id, email, created_at, status, spec_json) VALUES(?,?,?,?,?)",
                (job_id, email or "", time.time(), "queued", json.dumps(spec)))
        return job_id

    def get_job(self, job_id: str) -> dict | None:
        row = self._x("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        for k in ("spec_json", "result_json", "progress_json"):
            d[k[:-5]] = json.loads(d.pop(k)) if d.get(k) else None
        return d

    def update_job(self, job_id: str, **fields) -> None:
        for k in ("result", "progress"):
            if k in fields:
                fields[f"{k}_json"] = json.dumps(fields.pop(k))
        cols = ", ".join(f"{k}=?" for k in fields)
        self._x(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), job_id))

    def unfinished_jobs(self) -> list[str]:
        return [r["id"] for r in self._x("SELECT id FROM jobs WHERE status IN ('queued','running') ORDER BY created_at")]

    # -- http cache -------------------------------------------------------------
    def cache_get(self, key: str, ttl_s: int) -> str | None:
        row = self._x("SELECT fetched_at, body FROM http_cache WHERE key=?", (key,)).fetchone()
        if row and time.time() - row["fetched_at"] < ttl_s:
            return row["body"]
        return None

    def cache_put(self, key: str, body: str) -> None:
        self._x("INSERT OR REPLACE INTO http_cache(key, fetched_at, body) VALUES(?,?,?)", (key, time.time(), body))
