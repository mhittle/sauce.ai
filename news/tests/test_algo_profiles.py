"""Tests for the multiple-saved-algorithms (profiles) routes.

Exercises the algo blueprint's profile create / activate / rename / delete
handlers against an in-memory `user_algorithms` store (same monkeypatch
pattern as test_signals.py) so they run without a real DB. The invariant
under test: exactly one row per user carries `is_active = 1`, because the
feed / firehose / digest resolvers all read `is_active = 1 ... LIMIT 1`.
"""

import json
import itertools

import pytest

from app import create_app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("app.db.close_conn", lambda exc=None: None)
    app = create_app()

    @app.before_request
    def _stub_user():
        from flask import g
        g.user = {"id": 42, "email": "t@x", "is_admin": 0}

    return app.test_client()


@pytest.fixture
def store(monkeypatch):
    """In-memory user_algorithms model + scripted SQL fakes."""
    rows = []                       # list of dicts
    ids = itertools.count(1)
    clock = itertools.count(1)      # stand-in for updated_at ordering

    def _touch(r):
        r["updated_at"] = next(clock)

    def fake_query(sql, params=None, one=False):
        s = " ".join(sql.split()).lower()
        if s.startswith("select id from user_algorithms where id = %s and user_id = %s"):
            aid, uid = params
            m = [r for r in rows if r["id"] == aid and r["user_id"] == uid]
            return ({"id": m[0]["id"]} if m else None) if one else m
        if s.startswith("select id from user_algorithms where user_id = %s and name = %s"):
            uid, name = params
            m = [r for r in rows if r["user_id"] == uid and r["name"] == name]
            m.sort(key=lambda r: r["updated_at"], reverse=True)
            return ({"id": m[0]["id"]} if m else None) if one else m
        if "from user_algorithms" in s and "order by is_active desc" in s:
            (uid,) = params
            mine = [r for r in rows if r["user_id"] == uid]
            mine.sort(key=lambda r: (r["is_active"], r["updated_at"]), reverse=True)
            return [{"id": r["id"], "name": r["name"], "is_active": r["is_active"]}
                    for r in mine]
        return None if one else []

    def fake_execute(sql, params=None):
        s = " ".join(sql.split()).lower()
        if s.startswith("insert into user_algorithms"):
            uid, name, wj, expr = params
            r = {"id": next(ids), "user_id": uid, "name": name,
                 "weights_json": wj, "expression_text": expr, "is_active": 0}
            _touch(r)
            rows.append(r)
            return r["id"]   # mirrors db.execute -> cur.lastrowid
        elif s.startswith("update user_algorithms set weights_json=%s, expression_text=%s where id=%s and user_id=%s"):
            wj, expr, aid, uid = params
            for r in rows:
                if r["id"] == aid and r["user_id"] == uid:
                    r["weights_json"] = wj
                    r["expression_text"] = expr
                    _touch(r)
        elif s.startswith("update user_algorithms set is_active = 0 where user_id = %s"):
            (uid,) = params
            for r in rows:
                if r["user_id"] == uid:
                    r["is_active"] = 0
                    _touch(r)
        elif s.startswith("update user_algorithms set is_active = 1 where id = %s and user_id = %s"):
            aid, uid = params
            for r in rows:
                if r["id"] == aid and r["user_id"] == uid:
                    r["is_active"] = 1
                    _touch(r)
        elif s.startswith("update user_algorithms set name = %s where id = %s and user_id = %s"):
            name, aid, uid = params
            for r in rows:
                if r["id"] == aid and r["user_id"] == uid:
                    r["name"] = name
                    _touch(r)
        elif s.startswith("delete from user_algorithms where id = %s and user_id = %s"):
            aid, uid = params
            rows[:] = [r for r in rows if not (r["id"] == aid and r["user_id"] == uid)]
        return 1

    class FakeConn:
        def commit(self):
            pass

    monkeypatch.setattr("app.routes.algo.query", fake_query)
    monkeypatch.setattr("app.routes.algo.execute", fake_execute)
    monkeypatch.setattr("app.routes.algo.get_conn", lambda: FakeConn())

    def seed(name, active=0):
        r = {"id": next(ids), "user_id": 42, "name": name,
             "weights_json": "{}", "expression_text": "", "is_active": active}
        r["updated_at"] = next(clock)
        rows.append(r)
        return r["id"]

    return {"rows": rows, "seed": seed}


def _active_ids(rows):
    return [r["id"] for r in rows if r["is_active"]]


def test_create_profile_inserts_and_activates(client, store):
    store["seed"]("Old", active=1)
    r = client.post("/algo/profiles/create",
                     data={"profile_name": "Morning brief", "w_objectivity": "1.5"})
    assert r.status_code == 302
    new = [x for x in store["rows"] if x["name"] == "Morning brief"][0]
    assert _active_ids(store["rows"]) == [new["id"]]      # exactly one active
    assert json.loads(new["weights_json"])["objectivity"] == 1.5


def test_create_profile_blank_name_defaults(client, store):
    client.post("/algo/profiles/create", data={"profile_name": "   "})
    assert store["rows"][-1]["name"] == "Custom"


def test_create_profile_reuses_same_name_instead_of_duplicating(client, store):
    """BUG-025: re-saving an existing profile name overwrites it and
    activates it rather than stacking a duplicate row."""
    other = store["seed"]("Other", active=1)
    existing = store["seed"]("Lefty", active=0)
    r = client.post("/algo/profiles/create",
                    data={"profile_name": "Lefty", "w_objectivity": "1.5"})
    assert r.status_code == 302
    lefties = [x for x in store["rows"] if x["name"] == "Lefty"]
    assert len(lefties) == 1                     # no duplicate created
    assert lefties[0]["id"] == existing          # reused the existing row
    assert json.loads(lefties[0]["weights_json"])["objectivity"] == 1.5
    assert _active_ids(store["rows"]) == [existing]   # exactly one active


def test_create_profile_distinct_name_inserts_new_row(client, store):
    store["seed"]("Lefty", active=1)
    client.post("/algo/profiles/create", data={"profile_name": "Righty"})
    names = sorted(r["name"] for r in store["rows"])
    assert names == ["Lefty", "Righty"]


def test_activate_switches_single_active(client, store):
    a = store["seed"]("A", active=1)
    b = store["seed"]("B", active=0)
    r = client.post("/algo/profiles/activate", data={"algo_id": str(b)})
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/algo/")
    assert _active_ids(store["rows"]) == [b]
    assert a not in _active_ids(store["rows"])


def test_activate_return_to_feed_redirects_home(client, store):
    store["seed"]("A", active=1)
    b = store["seed"]("B")
    r = client.post("/algo/profiles/activate",
                     data={"algo_id": str(b), "return_to": "feed"})
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/")
    assert not r.headers["Location"].endswith("/algo/")


def test_activate_foreign_id_is_noop(client, store):
    a = store["seed"]("A", active=1)
    r = client.post("/algo/profiles/activate", data={"algo_id": "9999"})
    assert r.status_code == 302
    assert _active_ids(store["rows"]) == [a]   # unchanged


def test_rename_profile(client, store):
    a = store["seed"]("Old name", active=1)
    client.post("/algo/profiles/rename",
                data={"algo_id": str(a), "profile_name": "Weekend deep-dive"})
    assert store["rows"][0]["name"] == "Weekend deep-dive"


def test_delete_profile_removes_when_multiple(client, store):
    a = store["seed"]("A", active=1)
    b = store["seed"]("B")
    client.post("/algo/profiles/delete", data={"algo_id": str(b)})
    assert [r["id"] for r in store["rows"]] == [a]


def test_delete_last_profile_refused(client, store):
    a = store["seed"]("Only", active=1)
    r = client.post("/algo/profiles/delete", data={"algo_id": str(a)})
    assert r.status_code == 302
    assert [r["id"] for r in store["rows"]] == [a]   # still there


def test_delete_active_promotes_survivor(client, store):
    a = store["seed"]("A", active=1)
    b = store["seed"]("B", active=0)
    client.post("/algo/profiles/delete", data={"algo_id": str(a)})
    assert [r["id"] for r in store["rows"]] == [b]
    assert _active_ids(store["rows"]) == [b]          # invariant preserved


def test_profile_routes_require_login(monkeypatch, store):
    monkeypatch.setattr("app.db.close_conn", lambda exc=None: None)
    app = create_app()
    c = app.test_client()
    for path in ("/algo/profiles/create", "/algo/profiles/activate",
                 "/algo/profiles/rename", "/algo/profiles/delete"):
        r = c.post(path, data={})
        assert r.status_code == 302
        assert "/auth/login" in r.headers["Location"]
