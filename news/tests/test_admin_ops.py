"""Unit tests for the admin_ops blueprint (post-deploy verification feed).

Exercises the two read-only endpoints with monkeypatched `query` and a
stubbed admin user, mirroring the test_signals.py pattern. No real DB or
log file is touched except a tmp file for the cron-health tail test.
"""

import json
from datetime import date

import pytest

from app import create_app


def _app_with_user(monkeypatch, user):
    monkeypatch.setattr("app.db.close_conn", lambda exc=None: None)
    app = create_app()

    @app.before_request
    def _stub_user():
        from flask import g
        g.user = user

    return app


@pytest.fixture
def admin_client(monkeypatch):
    return _app_with_user(
        monkeypatch, {"id": 1, "email": "a@x", "is_admin": 1}
    ).test_client()


# --- auth -----------------------------------------------------------------

def test_cron_health_requires_login(monkeypatch):
    app = _app_with_user(monkeypatch, None)
    r = app.test_client().get("/admin/cron-health")
    assert r.status_code == 302  # redirect to login


def test_cron_health_forbidden_for_non_admin(monkeypatch):
    app = _app_with_user(monkeypatch, {"id": 9, "email": "u@x", "is_admin": 0})
    r = app.test_client().get("/admin/cron-health")
    assert r.status_code == 403


def test_usage_summary_requires_admin(monkeypatch):
    app = _app_with_user(monkeypatch, {"id": 9, "email": "u@x", "is_admin": 0})
    r = app.test_client().get("/admin/usage-summary")
    assert r.status_code == 403


# --- cron-health ----------------------------------------------------------

def test_cron_health_missing_file(admin_client, monkeypatch, tmp_path):
    missing = str(tmp_path / "nope.log")
    monkeypatch.setenv("CRON_LOG_PATH", missing)
    r = admin_client.get("/admin/cron-health")
    assert r.status_code == 200
    assert r.mimetype == "text/plain"
    assert b"cron log not found" in r.data


def test_cron_health_tails_last_200_lines(admin_client, monkeypatch, tmp_path):
    log = tmp_path / "cron.log"
    log.write_text("".join(f"line {i}\n" for i in range(500)), encoding="utf-8")
    monkeypatch.setenv("CRON_LOG_PATH", str(log))
    r = admin_client.get("/admin/cron-health")
    assert r.status_code == 200
    assert r.mimetype == "text/plain"
    body = r.data.decode()
    lines = body.splitlines()
    assert len(lines) == 200
    assert lines[0] == "line 300"
    assert lines[-1] == "line 499"


# --- usage-summary --------------------------------------------------------

@pytest.fixture
def usage_query(monkeypatch):
    today = date(2026, 5, 21)

    def fake_query(sql, params=None, one=False):
        s = " ".join(sql.split()).lower()
        if "select utc_date() as d" in s:
            return {"d": today}
        if "from users" in s:
            return [{"d": date(2026, 5, 20), "n": 3},
                    {"d": date(2026, 5, 21), "n": 1}]
        if "user_clicks" in s:  # the DAU union query
            return [{"d": date(2026, 5, 21), "n": 7}]
        if "from user_signals" in s:  # signals-per-day
            return [{"d": date(2026, 5, 19), "n": 12}]
        return [] if not one else None

    monkeypatch.setattr("app.routes.admin_ops.query", fake_query)
    return today


def test_usage_summary_shape_and_merge(admin_client, usage_query):
    r = admin_client.get("/admin/usage-summary")
    assert r.status_code == 200
    data = json.loads(r.data)

    assert data["window_days"] == 14
    assert len(data["days"]) == 14
    # Oldest first, today last.
    assert data["days"][0]["date"] == "2026-05-08"
    assert data["days"][-1]["date"] == "2026-05-21"

    by_date = {d["date"]: d for d in data["days"]}
    assert by_date["2026-05-20"]["signups"] == 3
    assert by_date["2026-05-21"]["signups"] == 1
    assert by_date["2026-05-21"]["dau"] == 7
    assert by_date["2026-05-19"]["signals"] == 12
    # A day with no activity is zero-filled, not missing.
    assert by_date["2026-05-10"] == {
        "date": "2026-05-10", "signups": 0, "dau": 0, "signals": 0
    }

    assert data["totals"]["signups"] == 4
    assert data["totals"]["signals"] == 12
    assert data["totals"]["dau_peak"] == 7


# --- agent-activity -------------------------------------------------------

def test_agent_activity_requires_admin(monkeypatch):
    app = _app_with_user(monkeypatch, {"id": 9, "email": "u@x", "is_admin": 0})
    r = app.test_client().get("/admin/agent-activity")
    assert r.status_code == 403


def test_agent_activity_aggregates_and_zero_fills(admin_client, monkeypatch):
    today = date(2026, 5, 22)

    per_workflow = [
        {"workflow": "dev-agent", "runs": 2, "successes": 2, "failures": 0,
         "cost_usd": 16.0, "duration_s": 1200},
        {"workflow": "qa-code", "runs": 5, "successes": 4, "failures": 1,
         "cost_usd": 5.0, "duration_s": 300},
    ]
    per_day = [
        {"d": date(2026, 5, 21), "runs": 4, "cost_usd": 14.0},
        {"d": today,             "runs": 3, "cost_usd": 7.0},
    ]

    def fake_query(sql, params=None, one=False):
        s = " ".join(sql.split()).lower()
        if "select utc_date() as d" in s:
            return {"d": today}
        if "group by workflow" in s:
            return per_workflow
        if "from agent_runs" in s and "group by d" in s:
            return per_day
        return [] if not one else None

    monkeypatch.setattr("app.routes.admin_ops.query", fake_query)
    r = admin_client.get("/admin/agent-activity")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["window_days"] == 14
    assert data["table_missing"] is False
    assert len(data["per_day"]) == 14
    assert data["per_day"][-1] == {"date": "2026-05-22", "runs": 3, "cost_usd": 7.0}
    assert data["per_day"][-2] == {"date": "2026-05-21", "runs": 4, "cost_usd": 14.0}
    # A day with no rows is zero-filled.
    assert data["per_day"][0] == {"date": "2026-05-09", "runs": 0, "cost_usd": 0.0}

    by_wf = {w["workflow"]: w for w in data["per_workflow"]}
    assert by_wf["dev-agent"]["runs"] == 2
    assert by_wf["dev-agent"]["successes"] == 2
    assert by_wf["dev-agent"]["cost_usd"] == 16.0
    assert by_wf["qa-code"]["failures"] == 1

    assert data["totals"]["runs"] == 7
    assert data["totals"]["successes"] == 6
    assert data["totals"]["failures"] == 1
    assert data["totals"]["cost_usd"] == 21.0


def test_agent_activity_degrades_when_table_missing(admin_client, monkeypatch):
    def fake_query(sql, params=None, one=False):
        # MySQL "Table 'x.agent_runs' doesn't exist" error class.
        raise RuntimeError("(1146, \"Table 'lt1ih6uyy2z6_news.agent_runs' doesn't exist\")")

    monkeypatch.setattr("app.routes.admin_ops.query", fake_query)
    r = admin_client.get("/admin/agent-activity")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["table_missing"] is True
    assert data["per_workflow"] == []
    assert data["per_day"] == []
    assert data["totals"] == {"runs": 0, "successes": 0, "failures": 0, "cost_usd": 0.0}
