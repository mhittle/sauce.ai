"""Integration smoke tests for the /local (News Near You) route.

The pure precedence/cookie logic is covered by test_geo_local.py. This
suite exercises the Flask layer: blueprint registration, the empty
state, the "couldn't resolve" state, the happy path (the route reaches
the feed query with the geo filter injected), and the persist-cookie
contract on a fresh resolve.

The DB is stubbed end-to-end so the test never opens a connection.
"""
import pytest

from app import create_app


@pytest.fixture
def anon_client(monkeypatch):
    monkeypatch.setattr("app.db.close_conn", lambda exc=None: None)
    app = create_app()
    return app.test_client()


@pytest.fixture
def feed_stub(monkeypatch):
    """Stub every query/db call the /local route makes. Captures the
    *last* feed-SELECT params so tests can assert geo_lat/geo_lng/geo_r
    were threaded through into the haversine clause."""
    captured = {"params": None, "sql": None}

    def fake_query(sql, params=None, one=False):
        s = " ".join(sql.split()).lower()
        if s.startswith("select id, weights_json from user_algorithms"):
            return None  # anon path; route falls back to default_weights
        if "from articles a" in s and "article_features f" in s:
            captured["sql"] = sql
            captured["params"] = params
            return []
        if "select article_id, signal_type" in s:
            return []
        if "from algorithm_term_prefs" in s:
            return []
        if "from user_saves" in s:
            return []
        if "from popularity_signals" in s:
            return []
        return None if one else []

    monkeypatch.setattr("app.routes.local.query", fake_query)
    monkeypatch.setattr("app.discussion.query", fake_query)
    return captured


def test_empty_state_when_no_place(anon_client, feed_stub):
    r = anon_client.get("/local")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Set your location" in body
    # No feed query should have been issued.
    assert feed_stub["params"] is None


def test_resolves_known_place_runs_query_and_sets_cookie(anon_client, feed_stub):
    r = anon_client.get("/local?place=Seattle%2C+WA&radius=25")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Seattle" in body
    # Feed query ran with the geo filter wired through.
    params = feed_stub["params"]
    assert params is not None
    assert 47.4 < params["geo_lat"] < 47.8
    assert params["geo_r"] == 25.0
    # A fresh resolve persists the cookie for the next visit.
    set_cookie = r.headers.get("Set-Cookie", "")
    assert "local_place=" in set_cookie


def test_unresolvable_place_renders_friendly_message(anon_client, feed_stub):
    r = anon_client.get("/local?place=zzznotacity")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Couldn't find" in body
    # No feed query issued — fell through with nothing to fall back on.
    assert feed_stub["params"] is None


def test_cookie_hit_does_not_repersist(anon_client, feed_stub):
    anon_client.set_cookie(
        "local_place",
        '{"lat":40.7,"lng":-74.0,"label":"NYC","radius":30.0}',
    )
    r = anon_client.get("/local")
    assert r.status_code == 200
    # Cookie hit -> no Set-Cookie (or at least no local_place re-set).
    set_cookie = r.headers.get("Set-Cookie", "") or ""
    assert "local_place=" not in set_cookie
    # And the geo filter rode the cookie's values through to SQL.
    params = feed_stub["params"]
    assert params is not None
    assert params["geo_lat"] == 40.7
    assert params["geo_r"] == 30.0


def test_nav_link_renders_on_base(anon_client, feed_stub):
    r = anon_client.get("/local")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert 'href="/local"' in body
    assert "Near You" in body
