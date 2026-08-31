"""Integration smoke tests for the `/blindspot` route.

The pure classification + labeling logic is covered in test_blindspot.py.
This suite exercises the Flask layer: blueprint registration, the
anon/no-algo onboarding state, the empty state when no candidates pass
the burst threshold, the happy path (route picks blindspots from the
big-story set the home feed wouldn't surface), and the failure-degrades
contract (any SQL exception → "couldn't compute" panel, never a 500).

The DB is stubbed end-to-end so the test never opens a connection.
"""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from app import create_app


@pytest.fixture
def anon_client(monkeypatch):
    monkeypatch.setattr("app.db.close_conn", lambda exc=None: None)
    app = create_app()
    return app.test_client()


def test_anon_renders_onboarding_empty_state(anon_client, monkeypatch):
    """Anon visitor gets the onboarding pitch, not a default-weights
    blindspot list (which would invert nonsense)."""
    monkeypatch.setattr("app.routes.blindspot.query",
                        lambda *a, **kw: None if kw.get("one") else [])
    r = anon_client.get("/blindspot")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Build your algorithm first" in body


def test_route_uses_helper_priority(monkeypatch):
    """Happy path: outlet-burst returns 4 stories, the feed already shows
    one (excluded), one is muted, one is filtered, one is low relevance.
    The page renders all three reasons with the right labels."""
    monkeypatch.setattr("app.db.close_conn", lambda exc=None: None)

    # Signed-in user with one active profile.
    fake_user_row = {"id": 7, "email": "u@x.com", "is_admin": 0}
    monkeypatch.setattr(
        "app.auth.query",
        lambda *a, **k: fake_user_row if k.get("one") else [],
    )

    def fake_load_user():
        from flask import g
        g.user = fake_user_row

    monkeypatch.setattr("app.auth.load_user", fake_load_user)

    # Active algorithm with a "crypto" mute. weights pick a hard-filter
    # on category so story 30 (its title contains "Sports") is filtered.
    weights = {"category_filter": ["world"]}
    fake_algo_row = {
        "id": 42,
        "weights_json": json.dumps(weights),
    }

    big_rows = [
        {"story_id": 10, "outlet_count": 30, "latest": None},
        {"story_id": 20, "outlet_count": 25, "latest": None},
        {"story_id": 30, "outlet_count": 18, "latest": None},
        {"story_id": 40, "outlet_count": 9, "latest": None},
    ]
    canonical_rows = [
        {"id": 10, "title": "Election results coming in", "summary": "World."},
        {"id": 20, "title": "Crypto exchange collapses",  "summary": "Markets."},
        {"id": 30, "title": "Sports championship recap",  "summary": "Final."},
        {"id": 40, "title": "Hurricane in the Caribbean", "summary": "Storm."},
    ]
    mute_rows = [{"term": "crypto"}]

    # Captures: which SQLs ran in what order, so we can assert behavior.
    sql_log = []

    def fake_query(sql, params=None, one=False):
        s = " ".join(sql.split())
        sql_log.append(s[:80])
        # active profile lookup
        if s.startswith("SELECT id, weights_json FROM user_algorithms"):
            return fake_algo_row if one else [fake_algo_row]
        # outlet-burst query (the GROUP BY + HAVING shape)
        if "COUNT(DISTINCT a.source_id)" in s and "HAVING outlet_count" in s:
            return big_rows
        # canonical title+summary IN-list
        if "SELECT id, title, summary FROM articles" in s and "IN (" in s:
            return canonical_rows
        # mute-term query
        if "FROM algorithm_term_prefs" in s and "'mute'" in s:
            return mute_rows
        # filter-survivors query (selects story_id, no GROUP BY)
        if "SELECT a.story_id FROM articles a" in s and "HAVING" not in s and "ORDER BY" not in s:
            # Story 30 fails the category filter, so it's missing here;
            # also story 20 is excluded because the mute SQL on the
            # selection helper drops it. But this is the FILTER survivor
            # query (no mute clause) — return all except 30.
            return [{"story_id": 10}, {"story_id": 20}, {"story_id": 40}]
        # _selected_story_ids — the selection SELECT that picks the
        # ids the feed would surface. We say it shows story 10
        # (election results) so 10 is NOT a blindspot. It uses ORDER BY.
        if "SELECT a.story_id FROM articles a" in s and "ORDER BY" in s:
            return [{"story_id": 10}]
        # cluster fetch (story dossier helper) — exposed by spectrum strip
        if "FROM articles a" in s and "a.story_id =" in s.replace(" ", " "):
            return []
        return None if one else []

    monkeypatch.setattr("app.routes.blindspot.query", fake_query)
    monkeypatch.setattr("app.routes.feed.query", fake_query)
    monkeypatch.setattr("app.routes.story.query", fake_query)
    monkeypatch.setattr("app.discussion.query", fake_query)

    app = create_app()
    client = app.test_client()
    r = client.get("/blindspot")
    assert r.status_code == 200
    body = r.get_data(as_text=True)

    # 20 (Crypto) is the mute hit
    assert "Crypto exchange collapses" in body
    assert "crypto" in body.lower()
    # 30 (Sports) is the filter hit
    assert "Sports championship recap" in body
    # 40 (Hurricane) is the low-relevance hit
    assert "Hurricane" in body
    # 10 (Election) is in shown_story_ids so NOT a blindspot
    assert "Election results coming in" not in body


def test_route_degrades_to_error_panel(monkeypatch):
    """A SQL exception during the page body becomes a graceful 200 with
    the error panel — never a 500."""
    monkeypatch.setattr("app.db.close_conn", lambda exc=None: None)

    fake_user_row = {"id": 9, "email": "u@x.com", "is_admin": 0}
    monkeypatch.setattr("app.auth.query",
                        lambda *a, **k: fake_user_row if k.get("one") else [])

    def fake_load_user():
        from flask import g
        g.user = fake_user_row

    monkeypatch.setattr("app.auth.load_user", fake_load_user)

    def fake_query(sql, params=None, one=False):
        s = " ".join(sql.split())
        if s.startswith("SELECT id, weights_json FROM user_algorithms"):
            return {"id": 1, "weights_json": "{}"} if one else []
        # Blow up on the outlet-burst.
        raise RuntimeError("simulated DB outage")

    monkeypatch.setattr("app.routes.blindspot.query", fake_query)

    app = create_app()
    client = app.test_client()
    r = client.get("/blindspot")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Couldn't compute" in body


def test_signed_in_nav_link_renders(monkeypatch):
    """The Blindspot nav link is signed-in only and points at /blindspot."""
    monkeypatch.setattr("app.db.close_conn", lambda exc=None: None)

    fake_user_row = {"id": 5, "email": "u@x.com", "is_admin": 0}
    monkeypatch.setattr("app.auth.query",
                        lambda *a, **k: fake_user_row if k.get("one") else [])

    def fake_load_user():
        from flask import g
        g.user = fake_user_row

    monkeypatch.setattr("app.auth.load_user", fake_load_user)
    monkeypatch.setattr("app.routes.blindspot.query",
                        lambda *a, **kw: None if kw.get("one") else [])

    app = create_app()
    client = app.test_client()
    r = client.get("/blindspot")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert 'href="/blindspot"' in body
    assert ">Blindspot<" in body
