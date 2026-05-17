"""Unit tests for the saves (bookmark) blueprint.

Same approach as test_signals.py: monkeypatch query/execute/get_conn so
the route handlers run without a real DB. CSRF is disabled suite-wide by
conftest, so POSTs need no token.
"""
from datetime import datetime

import pytest

from app import create_app
from app.routes import saves as saves_mod


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
def anon_client(monkeypatch):
    monkeypatch.setattr("app.db.close_conn", lambda exc=None: None)
    app = create_app()
    return app.test_client()


@pytest.fixture
def store(monkeypatch):
    saved = set()              # (user_id, article_id)
    executed = []
    query_responses = []

    def fake_query(sql, params=None, one=False):
        s = " ".join(sql.split()).lower()
        if "select 1 from user_saves where user_id" in s:
            uid, aid = params
            return {"x": 1} if (uid, aid) in saved else None
        if "from user_saves us" in s and "join articles a" in s:
            if query_responses:
                return query_responses.pop(0)
            return []
        if query_responses:
            r = query_responses.pop(0)
            return r if (one or r is None or isinstance(r, list)) else [r]
        return None if one else []

    def fake_execute(sql, params=None):
        executed.append((sql.strip().split()[0].upper(), params))
        s = " ".join(sql.split()).lower()
        if s.startswith("insert into user_saves"):
            uid, aid = params[0], params[1]
            saved.add((uid, aid))
        elif s.startswith("delete from user_saves"):
            uid, aid = params
            saved.discard((uid, aid))
        return 1

    class FakeConn:
        def commit(self):
            pass

    monkeypatch.setattr("app.routes.saves.query", fake_query)
    monkeypatch.setattr("app.routes.saves.execute", fake_execute)
    monkeypatch.setattr("app.routes.saves.get_conn", lambda: FakeConn())

    return {"saved": saved, "executed": executed, "query_responses": query_responses}


def test_toggle_saves_fresh_article(client, store):
    r = client.post("/save/100")
    assert r.status_code == 200
    assert r.get_json() == {"saved": True}
    assert (42, 100) in store["saved"]


def test_toggle_twice_unsaves(client, store):
    client.post("/save/100")
    r = client.post("/save/100")
    assert r.get_json() == {"saved": False}
    assert (42, 100) not in store["saved"]


def test_toggle_requires_auth(anon_client, store):
    r = anon_client.post("/save/100")
    assert r.status_code == 401


def test_custom_folder_is_passed_through(client, store):
    client.post("/save/100", data={"folder": "Research"})
    ins = [e for e in store["executed"] if e[0] == "INSERT"]
    assert ins and ins[-1][1] == (42, 100, "Research")


def test_blank_folder_falls_back_to_default(client, store):
    client.post("/save/100", data={"folder": "   "})
    ins = [e for e in store["executed"] if e[0] == "INSERT"]
    assert ins[-1][1] == (42, 100, "Read Later")


def test_mark_read_issues_update(client, store):
    r = client.post("/save/100/read")
    assert r.status_code == 204
    ups = [e for e in store["executed"] if e[0] == "UPDATE"]
    assert ups and ups[-1][1] == (42, 100)


def test_mark_read_requires_auth(anon_client, store):
    r = anon_client.post("/save/100/read")
    assert r.status_code == 401


def test_saved_page_redirects_anon(anon_client, store):
    r = anon_client.get("/saved")
    assert r.status_code == 302
    assert "/auth/login" in r.headers["Location"]


def test_saved_page_lists_items(client, store):
    store["query_responses"].append([
        {
            "id": 7, "title": "Durable headline", "url": "https://x/a",
            "byline": "A. Writer", "published_at": datetime(2026, 5, 10, 9, 0),
            "thumbnail_url": None, "source_name": "The Wire",
            "category": "world", "political_lean": -0.2,
            "body_status": "ok", "word_count": 800,
            "folder": "Read Later",
            "saved_at": datetime(2026, 5, 17, 8, 0), "read_at": None,
        }
    ])
    r = client.get("/saved")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Durable headline" in body
    assert "archived" in body  # body_status == ok -> durable-archive badge


def test_saved_page_empty_state(client, store):
    store["query_responses"].append([])
    r = client.get("/saved")
    assert r.status_code == 200
    assert "Nothing saved yet" in r.get_data(as_text=True)
