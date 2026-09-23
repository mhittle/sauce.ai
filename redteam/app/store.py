"""SQLite persistence (stdlib). One file, WAL mode, a process-wide write lock.

Target credentials are never written here: ``target_json`` holds
``TargetConfig.public_dict()`` only.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    created_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL,
    status TEXT NOT NULL,
    n_trials INTEGER NOT NULL,
    completed_trials INTEGER NOT NULL DEFAULT 0,
    config_json TEXT NOT NULL,
    target_json TEXT NOT NULL,
    summary_json TEXT,
    bandit_json TEXT,
    usage_json TEXT,
    report_html TEXT,
    error TEXT,
    emailed_at REAL,
    price_usd REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_runs_email ON runs(email);
CREATE TABLE IF NOT EXISTS trials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    arm TEXT NOT NULL,
    persona_json TEXT NOT NULL,
    status TEXT NOT NULL,
    n_turns INTEGER NOT NULL DEFAULT 0,
    first_harm_turn INTEGER,
    error TEXT,
    started_at REAL,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS ix_trials_run ON trials(run_id);
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trial_id INTEGER NOT NULL,
    run_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    tactic TEXT,
    degraded INTEGER NOT NULL DEFAULT 0,
    user_message TEXT NOT NULL,
    target_reply TEXT NOT NULL,
    orchestration_json TEXT,
    annotation_json TEXT NOT NULL,
    harmful INTEGER NOT NULL,
    p_harm REAL NOT NULL,
    expected_qaly_loss REAL NOT NULL,
    latency_ms INTEGER
);
CREATE INDEX IF NOT EXISTS ix_turns_trial ON turns(trial_id);
CREATE TABLE IF NOT EXISTS quota (
    email TEXT PRIMARY KEY,
    trials_used INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS adjudication_sets (
    id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    name TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    run_ids_json TEXT NOT NULL,
    n_items INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS adjudication_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    set_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    turn_id INTEGER NOT NULL,
    run_id TEXT NOT NULL,
    stratum TEXT NOT NULL,
    harm_bin TEXT NOT NULL,
    inclusion_prob REAL NOT NULL,
    judge_p_harm REAL,
    judge_harmful INTEGER,
    context_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_adjitems_set ON adjudication_items(set_id);
CREATE TABLE IF NOT EXISTS adjudication_labels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL,
    set_id TEXT NOT NULL,
    rater TEXT NOT NULL,
    harmful INTEGER NOT NULL,
    severity INTEGER,
    categories_json TEXT NOT NULL DEFAULT '[]',
    escalated INTEGER,
    confidence INTEGER,
    notes TEXT,
    created_at REAL NOT NULL,
    UNIQUE(item_id, rater)
);
CREATE INDEX IF NOT EXISTS ix_adjlabels_set ON adjudication_labels(set_id);
"""


class QuotaExceeded(Exception):
    def __init__(self, remaining: int) -> None:
        super().__init__(f"free-tier limit reached: {remaining} trials remaining")
        self.remaining = remaining


class Store:
    def __init__(self, path: str) -> None:
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        if path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)

    def _x(self, sql: str, args: tuple = ()):
        with self._lock:
            return self._conn.execute(sql, args)

    # -- quota --------------------------------------------------------------
    def trials_used(self, email: str) -> int:
        row = self._x("SELECT trials_used FROM quota WHERE email=?", (email,)).fetchone()
        return row["trials_used"] if row else 0

    def reserve_trials(self, email: str, n: int, limit: int) -> None:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                used = self.trials_used(email)
                if used + n > limit:
                    raise QuotaExceeded(max(0, limit - used))
                self._conn.execute(
                    "INSERT INTO quota(email, trials_used) VALUES(?, ?) "
                    "ON CONFLICT(email) DO UPDATE SET trials_used = trials_used + excluded.trials_used",
                    (email, n))
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def refund_trials(self, email: str, n: int) -> None:
        if n > 0:
            self._x("UPDATE quota SET trials_used = MAX(0, trials_used - ?) WHERE email=?", (n, email))

    # -- runs ---------------------------------------------------------------
    def create_run(self, email: str, n_trials: int, config: dict, target: dict, price_usd: float) -> str:
        run_id = uuid.uuid4().hex[:16]
        self._x("INSERT INTO runs(id, email, created_at, status, n_trials, config_json, target_json, price_usd) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (run_id, email, time.time(), "queued", n_trials, json.dumps(config), json.dumps(target), price_usd))
        return run_id

    def get_run(self, run_id: str) -> dict | None:
        row = self._x("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        for k in ("config_json", "target_json", "summary_json", "bandit_json", "usage_json"):
            d[k[:-5]] = json.loads(d.pop(k)) if d.get(k) else None
        return d

    def update_run(self, run_id: str, **fields) -> None:
        for k in ("summary", "bandit", "usage"):
            if k in fields:
                fields[f"{k}_json"] = json.dumps(fields.pop(k))
        cols = ", ".join(f"{k}=?" for k in fields)
        self._x(f"UPDATE runs SET {cols} WHERE id=?", (*fields.values(), run_id))

    def queued_runs(self) -> list[str]:
        return [r["id"] for r in self._x("SELECT id FROM runs WHERE status='queued' ORDER BY created_at")]

    def increment_completed(self, run_id: str) -> None:
        self._x("UPDATE runs SET completed_trials = completed_trials + 1 WHERE id=?", (run_id,))

    # -- trials / turns -----------------------------------------------------
    def create_trial(self, run_id: str, idx: int, arm: str, persona: dict) -> int:
        cur = self._x("INSERT INTO trials(run_id, idx, arm, persona_json, status, started_at) VALUES(?,?,?,?,?,?)",
                      (run_id, idx, arm, json.dumps(persona), "running", time.time()))
        return cur.lastrowid

    def finish_trial(self, trial_id: int, *, status: str, n_turns: int, first_harm_turn: int | None,
                     error: str | None = None) -> None:
        self._x("UPDATE trials SET status=?, n_turns=?, first_harm_turn=?, error=?, finished_at=? WHERE id=?",
                (status, n_turns, first_harm_turn, error, time.time(), trial_id))

    def add_turn(self, trial_id: int, run_id: str, idx: int, *, tactic: str, degraded: bool, user_message: str,
                 target_reply: str, orchestration: dict, annotation: dict, latency_ms: int) -> None:
        self._x("INSERT INTO turns(trial_id, run_id, idx, tactic, degraded, user_message, target_reply, "
                "orchestration_json, annotation_json, harmful, p_harm, expected_qaly_loss, latency_ms) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (trial_id, run_id, idx, tactic, int(degraded), user_message, target_reply,
                 json.dumps(orchestration), json.dumps(annotation), int(annotation["harmful"]),
                 annotation["p_harm"], annotation["expected_qaly_loss"], latency_ms))

    def trials_for_run(self, run_id: str, with_turns: bool = True) -> list[dict]:
        trials = [dict(r) for r in self._x("SELECT * FROM trials WHERE run_id=? ORDER BY idx", (run_id,))]
        for t in trials:
            t["persona"] = json.loads(t.pop("persona_json"))
            if with_turns:
                rows = self._x("SELECT * FROM turns WHERE trial_id=? ORDER BY idx", (t["id"],)).fetchall()
                t["turns"] = []
                for r in rows:
                    u = dict(r)
                    u["annotation"] = json.loads(u.pop("annotation_json"))
                    u["orchestration"] = json.loads(u.pop("orchestration_json") or "{}")
                    t["turns"].append(u)
        return trials

    # -- adjudication -------------------------------------------------------
    def create_adjudication_set(self, name: str, spec: dict, run_ids: list[str],
                                items: list[dict]) -> str:
        """items: dicts with turn_id, run_id, stratum, harm_bin, inclusion_prob,
        judge_p_harm, judge_harmful, context."""
        set_id = uuid.uuid4().hex[:16]
        with self._lock:
            self._conn.execute(
                "INSERT INTO adjudication_sets(id, created_at, name, spec_json, run_ids_json, n_items) "
                "VALUES(?,?,?,?,?,?)",
                (set_id, time.time(), name, json.dumps(spec), json.dumps(run_ids), len(items)))
            for pos, it in enumerate(items):
                self._conn.execute(
                    "INSERT INTO adjudication_items(set_id, position, turn_id, run_id, stratum, harm_bin, "
                    "inclusion_prob, judge_p_harm, judge_harmful, context_json) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (set_id, pos, it["turn_id"], it["run_id"], it["stratum"], it["harm_bin"],
                     it["inclusion_prob"], it.get("judge_p_harm"),
                     None if it.get("judge_harmful") is None else int(it["judge_harmful"]),
                     json.dumps(it["context"])))
        return set_id

    def get_adjudication_set(self, set_id: str) -> dict | None:
        row = self._x("SELECT * FROM adjudication_sets WHERE id=?", (set_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["spec"] = json.loads(d.pop("spec_json"))
        d["run_ids"] = json.loads(d.pop("run_ids_json"))
        return d

    def adjudication_items(self, set_id: str, blinded: bool = True) -> list[dict]:
        rows = self._x("SELECT * FROM adjudication_items WHERE set_id=? ORDER BY position", (set_id,)).fetchall()
        out = []
        for r in rows:
            it = dict(r)
            it["context"] = json.loads(it.pop("context_json"))
            if blinded:
                it.pop("judge_p_harm", None)
                it.pop("judge_harmful", None)
                it.pop("stratum", None)
                it.pop("harm_bin", None)
                it.pop("inclusion_prob", None)
            out.append(it)
        return out

    def submit_label(self, set_id: str, item_id: int, rater: str, *, harmful: bool,
                     severity: int | None, categories: list[str], escalated: bool | None,
                     confidence: int | None, notes: str | None) -> None:
        self._x(
            "INSERT INTO adjudication_labels(item_id, set_id, rater, harmful, severity, categories_json, "
            "escalated, confidence, notes, created_at) VALUES(?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(item_id, rater) DO UPDATE SET harmful=excluded.harmful, severity=excluded.severity, "
            "categories_json=excluded.categories_json, escalated=excluded.escalated, "
            "confidence=excluded.confidence, notes=excluded.notes, created_at=excluded.created_at",
            (item_id, set_id, rater, int(harmful), severity, json.dumps(categories),
             None if escalated is None else int(escalated), confidence, notes, time.time()))

    def adjudication_labels(self, set_id: str) -> list[dict]:
        rows = self._x("SELECT * FROM adjudication_labels WHERE set_id=? ORDER BY item_id, rater", (set_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["categories"] = json.loads(d.pop("categories_json"))
            d["harmful"] = bool(d["harmful"])
            d["escalated"] = None if d["escalated"] is None else bool(d["escalated"])
            out.append(d)
        return out

    def adjudication_progress(self, set_id: str) -> dict:
        raters = [r["rater"] for r in self._x(
            "SELECT DISTINCT rater FROM adjudication_labels WHERE set_id=? ORDER BY rater", (set_id,))]
        counts = {r["rater"]: r["c"] for r in self._x(
            "SELECT rater, COUNT(*) c FROM adjudication_labels WHERE set_id=? GROUP BY rater", (set_id,))}
        return {"raters": raters, "labeled_by_rater": counts}
