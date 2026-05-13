"""Unit tests for the signals blueprint.

These exercise the route handlers with monkeypatched `query` / `execute`
so they run without a real DB. Coverage focuses on the toggle semantics
and the 3+ downs prompt condition.
"""

import json

import pytest

from app import create_app
from app.routes import signals as signals_mod


@pytest.fixture
def client(monkeypatch):
    """App with a stub user and an in-memory signal store."""
    # Stop create_app from trying to open a real DB connection.
    monkeypatch.setattr("app.db.close_conn", lambda exc=None: None)
    app = create_app()

    # Stub auth: pretend user 42 is signed in for every request.
    @app.before_request
    def _stub_user():
        from flask import g
        g.user = {"id": 42, "email": "t@x", "is_admin": 0}

    return app.test_client()


@pytest.fixture
def store(monkeypatch):
    """Capture inserts/deletes + scripted query responses."""
    rows = {"signals": []}        # (user_id, article_id, signal_type)
    prefs = {}                    # (uid, sid) -> weight
    executed = []
    query_responses = []          # list of return values in order

    def fake_query(sql, params=None, one=False):
        s = " ".join(sql.split()).lower()
        if "from user_signals" in s and "signal_type in" in s and "thumb_up" in s and "select signal_type" in s:
            uid, aid = params
            matches = [{"signal_type": t} for (u, a, t) in rows["signals"]
                       if u == uid and a == aid and t in ("thumb_up", "thumb_down")]
            return matches
        if query_responses:
            r = query_responses.pop(0)
            return r if (one or r is None or isinstance(r, list)) else [r]
        return None if one else []

    def fake_execute(sql, params=None):
        executed.append((sql.strip().split()[0].upper(), params))
        s = " ".join(sql.split()).lower()
        if s.startswith("delete from user_signals"):
            uid, aid, st = params
            rows["signals"] = [r for r in rows["signals"]
                               if not (r[0] == uid and r[1] == aid and r[2] == st)]
        elif s.startswith("insert into user_signals"):
            uid, aid, st = params
            rows["signals"].append((uid, aid, st))
        elif s.startswith("insert into user_source_prefs"):
            uid, sid, w = params
            prefs[(uid, sid)] = w
        elif s.startswith("delete from user_source_prefs"):
            uid, sid = params
            prefs.pop((uid, sid), None)
        return 1

    class FakeConn:
        def commit(self):
            pass

    monkeypatch.setattr("app.routes.signals.query", fake_query)
    monkeypatch.setattr("app.routes.signals.execute", fake_execute)
    monkeypatch.setattr("app.routes.signals.get_conn", lambda: FakeConn())

    return {
        "rows": rows,
        "prefs": prefs,
        "executed": executed,
        "query_responses": query_responses,
    }


def test_thumb_up_on_fresh_article_inserts(client, store):
    r = client.post("/signal/100/thumb_up")
    assert r.status_code == 200
    data = r.get_json()
    assert data["state"] == "thumb_up"
    assert data["prompt"] is None
    assert (42, 100, "thumb_up") in store["rows"]["signals"]


def test_thumb_up_twice_toggles_off(client, store):
    client.post("/signal/100/thumb_up")
    r = client.post("/signal/100/thumb_up")
    assert r.get_json()["state"] is None
    assert (42, 100, "thumb_up") not in store["rows"]["signals"]


def test_thumb_up_replaces_existing_down(client, store):
    store["rows"]["signals"].append((42, 100, "thumb_down"))
    r = client.post("/signal/100/thumb_up")
    assert r.get_json()["state"] == "thumb_up"
    sigs = [t for (u, a, t) in store["rows"]["signals"] if a == 100]
    assert sigs == ["thumb_up"]


def test_thumb_down_with_3_prior_downs_triggers_prompt(client, store):
    store["query_responses"].append({"source_id": 7, "source_name": "Daily Boring", "n": 3})
    r = client.post("/signal/100/thumb_down")
    data = r.get_json()
    assert data["state"] == "thumb_down"
    assert data["prompt"] == {"source_id": 7, "source_name": "Daily Boring", "down_count": 3}


def test_thumb_down_with_fewer_downs_no_prompt(client, store):
    store["query_responses"].append({"source_id": 7, "source_name": "X", "n": 2})
    r = client.post("/signal/100/thumb_down")
    assert r.get_json()["prompt"] is None


def test_thumb_down_no_aggregate_row_no_prompt(client, store):
    store["query_responses"].append(None)
    r = client.post("/signal/100/thumb_down")
    assert r.get_json()["prompt"] is None


def test_thumb_up_does_not_query_for_prompt(client, store):
    # query_responses empty -> if vote() tried to read it, we'd still get None,
    # but we want to ensure prompt is always None for upvotes.
    r = client.post("/signal/100/thumb_up")
    assert r.get_json()["prompt"] is None


def test_unsupported_signal_type_400(client, store):
    r = client.post("/signal/100/dwell_ms")
    assert r.status_code == 400


def test_auth_required(monkeypatch, store):
    monkeypatch.setattr("app.db.close_conn", lambda exc=None: None)
    app = create_app()
    r = app.test_client().post("/signal/100/thumb_up")
    assert r.status_code == 401


def test_source_pref_hide_sets_weight_zero(client, store):
    r = client.post("/signal/source/7", data={"action": "hide"})
    assert r.status_code == 200
    assert store["prefs"][(42, 7)] == 0.0


def test_source_pref_downweight_sets_half(client, store):
    r = client.post("/signal/source/7", data={"action": "downweight"})
    assert store["prefs"][(42, 7)] == 0.5


def test_source_pref_reset_deletes(client, store):
    store["prefs"][(42, 7)] = 0.0
    r = client.post("/signal/source/7", data={"action": "reset"})
    assert (42, 7) not in store["prefs"]
    assert r.get_json()["weight"] is None


def test_source_pref_unknown_action_400(client, store):
    r = client.post("/signal/source/7", data={"action": "boost"})
    assert r.status_code == 400
