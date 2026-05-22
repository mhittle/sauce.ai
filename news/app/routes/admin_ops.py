"""Read-only operational endpoints for the post-deploy verification agent.

Three admin-only endpoints:

  GET /admin/cron-health    -> last N lines of logs/cron.log (text/plain)
  GET /admin/usage-summary  -> 14-day signups / DAU / signal counts (JSON)
  GET /admin/agent-activity -> 14-day agent fleet cost + run-count rollup
                               (JSON; read by the PM agent each week)

All read-only. `usage-summary` / `agent-activity` run only SELECTs;
`cron-health` only reads the log file. `agent-activity` degrades to
an empty rollup if the `agent_runs` table is missing (e.g. before the
2026-05-22-agent-runs.sql migration is applied on prod) so the
admin page never 500s.
"""

import os
from collections import deque
from datetime import datetime

from flask import Blueprint, Response, jsonify, current_app

from ..auth import admin_required
from ..db import query

bp = Blueprint("admin_ops", __name__)

CRON_LOG_TAIL_LINES = 200
USAGE_WINDOW_DAYS = 14
AGENT_ACTIVITY_WINDOW_DAYS = 14


def _cron_log_path() -> str:
    override = os.environ.get("CRON_LOG_PATH")
    if override:
        return override
    # current_app.root_path is .../news/app; the cron log lives at
    # .../news/logs/cron.log (same path the cPanel crontab appends to).
    return os.path.normpath(
        os.path.join(current_app.root_path, "..", "logs", "cron.log")
    )


@bp.route("/cron-health")
@admin_required
def cron_health():
    path = _cron_log_path()
    if not os.path.exists(path):
        return Response(
            f"cron log not found at {path}\n",
            mimetype="text/plain",
            status=200,
        )
    # Tail without slurping the whole file into memory.
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        tail = deque(fh, maxlen=CRON_LOG_TAIL_LINES)
    return Response("".join(tail), mimetype="text/plain")


@bp.route("/usage-summary")
@admin_required
def usage_summary():
    days = USAGE_WINDOW_DAYS
    span = days - 1

    signups = {
        r["d"]: r["n"]
        for r in query(
            """SELECT DATE(created_at) AS d, COUNT(*) AS n
               FROM users
               WHERE created_at >= UTC_DATE() - INTERVAL %s DAY
               GROUP BY d""",
            (span,),
        )
    }
    signals = {
        r["d"]: r["n"]
        for r in query(
            """SELECT DATE(created_at) AS d, COUNT(*) AS n
               FROM user_signals
               WHERE created_at >= UTC_DATE() - INTERVAL %s DAY
               GROUP BY d""",
            (span,),
        )
    }
    # DAU = distinct users active that day via a click or an explicit
    # signal. user_clicks.user_id is nullable (anon clicks) so filter it.
    dau = {
        r["d"]: r["n"]
        for r in query(
            """SELECT d, COUNT(*) AS n FROM (
                 SELECT DISTINCT user_id, DATE(ts) AS d
                 FROM user_clicks
                 WHERE user_id IS NOT NULL
                   AND ts >= UTC_DATE() - INTERVAL %s DAY
                 UNION
                 SELECT DISTINCT user_id, DATE(created_at) AS d
                 FROM user_signals
                 WHERE created_at >= UTC_DATE() - INTERVAL %s DAY
               ) x
               GROUP BY d""",
            (span, span),
        )
    }

    today = query("SELECT UTC_DATE() AS d", one=True)["d"]
    series = []
    for offset in range(span, -1, -1):
        day = today - _timedelta(offset)
        key = day.isoformat() if hasattr(day, "isoformat") else str(day)
        series.append({
            "date": key,
            "signups": int(_lookup(signups, day)),
            "dau": int(_lookup(dau, day)),
            "signals": int(_lookup(signals, day)),
        })

    return jsonify({
        "window_days": days,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "days": series,
        "totals": {
            "signups": sum(d["signups"] for d in series),
            "signals": sum(d["signals"] for d in series),
            "dau_peak": max((d["dau"] for d in series), default=0),
        },
    })


@bp.route("/agent-activity")
@admin_required
def agent_activity():
    """14-day agent fleet rollup: per-workflow totals + per-day series.

    Reads the append-only `agent_runs` table populated by each
    workflow's final `/agent-ops/report-run` step. If the table is
    missing (migration not yet applied), returns an empty rollup with
    a `table_missing: true` flag rather than 500'ing the admin page.
    """
    days = AGENT_ACTIVITY_WINDOW_DAYS
    span = days - 1

    try:
        per_workflow = query(
            """SELECT workflow,
                      COUNT(*) AS runs,
                      SUM(CASE WHEN conclusion = 'success' THEN 1 ELSE 0 END) AS successes,
                      SUM(CASE WHEN conclusion = 'failure' THEN 1 ELSE 0 END) AS failures,
                      COALESCE(SUM(est_cost_usd), 0) AS cost_usd,
                      COALESCE(SUM(duration_seconds), 0) AS duration_s
               FROM agent_runs
               WHERE ts >= UTC_DATE() - INTERVAL %s DAY
               GROUP BY workflow
               ORDER BY workflow""",
            (span,),
        )
        per_day_rows = query(
            """SELECT DATE(ts) AS d,
                      COUNT(*) AS runs,
                      COALESCE(SUM(est_cost_usd), 0) AS cost_usd
               FROM agent_runs
               WHERE ts >= UTC_DATE() - INTERVAL %s DAY
               GROUP BY d
               ORDER BY d""",
            (span,),
        )
    except Exception as exc:  # noqa: BLE001 — missing table / DB error: degrade
        msg = str(exc).lower()
        if "agent_runs" in msg and ("doesn't exist" in msg or "unknown" in msg):
            return jsonify({
                "window_days": days,
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "table_missing": True,
                "per_workflow": [],
                "per_day": [],
                "totals": {"runs": 0, "successes": 0, "failures": 0, "cost_usd": 0.0},
            })
        raise

    today = query("SELECT UTC_DATE() AS d", one=True)["d"]
    by_day = {r["d"]: r for r in per_day_rows}
    series = []
    for offset in range(span, -1, -1):
        day = today - _timedelta(offset)
        key = day.isoformat() if hasattr(day, "isoformat") else str(day)
        row = _lookup(by_day, day) or {}
        runs = int(row.get("runs", 0) or 0) if isinstance(row, dict) else 0
        cost = float(row.get("cost_usd", 0) or 0) if isinstance(row, dict) else 0.0
        series.append({"date": key, "runs": runs, "cost_usd": round(cost, 5)})

    per_workflow_out = []
    for r in per_workflow:
        per_workflow_out.append({
            "workflow": r["workflow"],
            "runs": int(r["runs"] or 0),
            "successes": int(r["successes"] or 0),
            "failures": int(r["failures"] or 0),
            "cost_usd": round(float(r["cost_usd"] or 0), 5),
            "duration_seconds": int(r["duration_s"] or 0),
        })

    return jsonify({
        "window_days": days,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "table_missing": False,
        "per_workflow": per_workflow_out,
        "per_day": series,
        "totals": {
            "runs": sum(w["runs"] for w in per_workflow_out),
            "successes": sum(w["successes"] for w in per_workflow_out),
            "failures": sum(w["failures"] for w in per_workflow_out),
            "cost_usd": round(sum(w["cost_usd"] for w in per_workflow_out), 5),
        },
    })


def _timedelta(n):
    from datetime import timedelta
    return timedelta(days=n)


def _lookup(mapping, day):
    """DATE() rows can come back as date objects or strings depending on
    the driver; match on either representation."""
    if day in mapping:
        return mapping[day]
    key = day.isoformat() if hasattr(day, "isoformat") else str(day)
    return mapping.get(key, 0)
