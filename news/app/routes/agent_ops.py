"""HMAC-authenticated executor for whitelisted prod operations.

Runs INSIDE the news Flask app and is driven by the GitHub Actions
migration-executor workflow. Three endpoints under `/agent-ops/*`, all
authenticated by an HMAC-SHA256 signature over the request body keyed
by `AGENT_OPS_SECRET` (set via .htaccess on prod):

  POST /agent-ops/run-migration  -> apply a whitelisted migration file
  POST /agent-ops/restart-app    -> touch the Passenger restart trigger
  POST /agent-ops/verify-schema  -> read-only column-existence check

This is the highest-blast-radius surface in the repo: it executes DDL
on the production database. The guard rails are, in order:

  1. HMAC signature with a freshness window (replay protection).
  2. Migration filename whitelist: basename only, `*.sql`, and the
     resolved path must live under `news/seed/migrations/`.
  3. verify-schema only ever runs a parameterized SELECT against
     `information_schema.columns` with identifier-validated inputs —
     it can never run caller-supplied SQL.

Note (documented in the Phase 4 PR): MySQL implicitly commits DDL, so
the single-transaction wrapper around run-migration gives real
rollback only for DML. Keep migrations idempotent
(`CREATE TABLE IF NOT EXISTS`, nullable-then-tighten ALTERs) so a
mid-migration failure is replay-safe.

The pure helpers (`compute_signature`, `verify_signature`,
`safe_migration_name`, `is_identifier`, `split_sql_statements`) import
no Flask so they stay unit-testable without the framework, matching the
convention in `app/security.py` / `app/language.py`.
"""

import hashlib
import hmac
import json
import os
import re
import time

from flask import Blueprint, Response, current_app, jsonify, request

from ..db import get_conn

bp = Blueprint("agent_ops", __name__)

SIGNATURE_HEADER = "X-Agent-Signature"
TIMESTAMP_HEADER = "X-Agent-Timestamp"
MAX_CLOCK_SKEW_SECONDS = 300

_MIGRATION_NAME_RE = re.compile(r"^[0-9A-Za-z._-]+\.sql$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_]+$")


# --- pure helpers (Flask-free) -------------------------------------------

def compute_signature(secret: str, timestamp: str, body: bytes) -> str:
    msg = timestamp.encode("utf-8") + b"." + body
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def verify_signature(
    secret: str,
    timestamp: str,
    body: bytes,
    provided_sig: str,
    now: int = None,
    max_skew: int = MAX_CLOCK_SKEW_SECONDS,
) -> bool:
    if not secret or not timestamp or not provided_sig:
        return False
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    now = int(time.time()) if now is None else now
    if abs(now - ts) > max_skew:
        return False
    expected = compute_signature(secret, timestamp, body)
    return hmac.compare_digest(expected, provided_sig)


def safe_migration_name(filename: str) -> bool:
    """True only for a bare `*.sql` basename with no path component."""
    if not filename or not isinstance(filename, str):
        return False
    if os.path.basename(filename) != filename:
        return False
    if filename in (".", "..") or "/" in filename or "\\" in filename:
        return False
    return bool(_MIGRATION_NAME_RE.match(filename))


def is_identifier(value: str, max_len: int = 64) -> bool:
    return bool(
        value
        and isinstance(value, str)
        and len(value) <= max_len
        and _IDENTIFIER_RE.match(value)
    )


def split_sql_statements(sql_text: str) -> list:
    """Split on `;`, drop comment-only / empty fragments.

    Naive by design (per spec) — the repo's migrations are plain DDL/DML
    with no semicolons inside string literals. Full-line `-- ` comments
    are stripped before deciding whether a fragment carries real SQL.
    """
    statements = []
    for raw in sql_text.split(";"):
        lines = [
            ln for ln in raw.splitlines() if not ln.strip().startswith("--")
        ]
        body = "\n".join(lines).strip()
        if body:
            statements.append(body)
    return statements


# --- internals -----------------------------------------------------------

def _migrations_dir() -> str:
    return os.path.realpath(
        os.path.join(current_app.root_path, "..", "seed", "migrations")
    )


def _restart_file() -> str:
    override = current_app.config.get("AGENT_OPS_RESTART_FILE") or os.environ.get(
        "AGENT_OPS_RESTART_FILE"
    )
    if override:
        return override
    # app_root is the dir holding `app/` (news/); the Passenger restart
    # trigger lives at <app_root>/../tmp/restart.txt on this host.
    app_root = os.path.dirname(current_app.root_path)
    return os.path.normpath(os.path.join(app_root, "..", "tmp", "restart.txt"))


def _authenticate():
    """Return (ok, error_response). error_response is None when ok."""
    secret = current_app.config.get("AGENT_OPS_SECRET") or os.environ.get(
        "AGENT_OPS_SECRET", ""
    )
    if not secret:
        return False, (
            jsonify({"status": "error", "error": "AGENT_OPS_SECRET not configured"}),
            503,
        )
    body = request.get_data()
    ts = request.headers.get(TIMESTAMP_HEADER, "")
    sig = request.headers.get(SIGNATURE_HEADER, "")
    if not verify_signature(secret, ts, body, sig):
        return False, (
            jsonify({"status": "error", "error": "signature verification failed"}),
            401,
        )
    return True, None


def _json_body():
    try:
        return json.loads(request.get_data() or b"{}")
    except (ValueError, TypeError):
        return None


# --- routes --------------------------------------------------------------

@bp.route("/run-migration", methods=["POST"])
def run_migration():
    ok, err = _authenticate()
    if not ok:
        return err

    payload = _json_body()
    if not isinstance(payload, dict):
        return jsonify({"status": "error", "error": "invalid JSON body"}), 400
    filename = payload.get("filename")
    if not safe_migration_name(filename):
        return jsonify({"status": "error", "error": "invalid migration filename"}), 400

    migrations_dir = _migrations_dir()
    path = os.path.realpath(os.path.join(migrations_dir, filename))
    if os.path.dirname(path) != migrations_dir:
        return jsonify({"status": "error", "error": "path outside migrations dir"}), 400
    if not os.path.isfile(path):
        return jsonify({"status": "error", "error": "migration file not found"}), 404

    with open(path, "r", encoding="utf-8") as fh:
        statements = split_sql_statements(fh.read())
    if not statements:
        return jsonify({"status": "error", "error": "no SQL statements in file"}), 400

    conn = get_conn()
    results = []
    try:
        with conn.cursor() as cur:
            for i, stmt in enumerate(statements):
                cur.execute(stmt)
                results.append({"stmt_index": i, "rowcount": cur.rowcount})
        conn.commit()
    except Exception as exc:  # noqa: BLE001 — any DB error rolls back
        conn.rollback()
        return (
            jsonify({
                "status": "error",
                "filename": filename,
                "error": str(exc),
                "failed_at": len(results),
                "statements_run": len(results),
            }),
            500,
        )

    return jsonify({
        "status": "ok",
        "filename": filename,
        "statements_run": len(statements),
        "results": results,
    })


@bp.route("/restart-app", methods=["POST"])
def restart_app():
    ok, err = _authenticate()
    if not ok:
        return err

    path = _restart_file()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a"):
            os.utime(path, None)
    except OSError as exc:
        return jsonify({"status": "error", "error": str(exc)}), 500
    return jsonify({"status": "ok", "restarted": True, "trigger": path})


@bp.route("/verify-schema", methods=["POST"])
def verify_schema():
    ok, err = _authenticate()
    if not ok:
        return err

    payload = _json_body()
    if not isinstance(payload, dict):
        return jsonify({"status": "error", "error": "invalid JSON body"}), 400
    table = payload.get("table")
    column = payload.get("column")
    if not is_identifier(table) or not is_identifier(column):
        return jsonify({"status": "error", "error": "invalid table or column"}), 400

    db_name = current_app.config.get("DB_NAME", "")
    row = None
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*) AS n
               FROM information_schema.columns
               WHERE table_schema = %s
                 AND table_name = %s
                 AND column_name = %s""",
            (db_name, table, column),
        )
        row = cur.fetchone()
    exists = bool(row and (row.get("n") if isinstance(row, dict) else row[0]))
    return jsonify({"table": table, "column": column, "exists": exists})
