"""Read-only operational endpoints for the post-deploy verification agent.

Two admin-only endpoints the GitHub Actions post-deploy QA workflow
hits after each deploy:

  GET /admin/cron-health   -> last N lines of logs/cron.log (text/plain)
  GET /admin/usage-summary -> 14-day signups / DAU / signal counts (JSON)

Both are read-only. `usage-summary` runs only SELECTs; `cron-health`
only reads the log file.
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
