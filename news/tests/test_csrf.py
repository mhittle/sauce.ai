"""Tests for the hand-rolled CSRF protection.

The pure-helper tests run without Flask. The integration tests follow the
`test_signals.py` pattern (create_app + test_client with the DB stubbed)
and exercise the before_request enforcement on a throwaway route plus the
RFC-8058 unsubscribe exemption.
"""

import pytest

from app.security import make_csrf_token, csrf_token_valid, tokens_match

SECRET = "unit-test-secret"


# --- pure helpers -------------------------------------------------------

def test_make_token_roundtrips_valid():
    t = make_csrf_token(SECRET)
    assert csrf_token_valid(t, SECRET)
    assert "." in t


def test_tampered_nonce_invalid():
    nonce, _, sig = make_csrf_token(SECRET).partition(".")
    assert csrf_token_valid(f"{nonce}x.{sig}", SECRET) is False


def test_tampered_signature_invalid():
    nonce, _, sig = make_csrf_token(SECRET).partition(".")
    flipped = "1" if sig[-1] == "0" else "0"
    assert csrf_token_valid(f"{nonce}.{sig[:-1]}{flipped}", SECRET) is False


def test_wrong_secret_invalid():
    assert csrf_token_valid(make_csrf_token(SECRET), "other-secret") is False


@pytest.mark.parametrize("bad", ["", "no-dot", ".", "nonce.", ".sig", None])
def test_malformed_tokens_invalid(bad):
    assert csrf_token_valid(bad, SECRET) is False


def test_tokens_match_constant_time_semantics():
    assert tokens_match("abc", "abc") is True
    assert tokens_match("abc", "abd") is False
    assert tokens_match("", "") is False
    assert tokens_match("abc", None) is False


# --- Flask integration --------------------------------------------------

@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr("app.db.close_conn", lambda exc=None: None)
    from app import create_app

    app = create_app()
    app.config["SECRET_KEY"] = SECRET
    app.config["CSRF_ENABLED"] = True  # conftest disables it suite-wide

    @app.route("/_csrf_probe", methods=["GET"])
    def _probe_get():
        from flask import g
        return g.csrf_token

    @app.route("/_csrf_probe", methods=["POST"])
    def _probe_post():
        return "ok"

    return app


def _token(client):
    return client.get("/_csrf_probe").get_data(as_text=True)


def test_get_sets_csrf_cookie(app):
    c = app.test_client()
    r = c.get("/_csrf_probe")
    assert r.status_code == 200
    assert "news_csrf" in r.headers.get("Set-Cookie", "")
    assert csrf_token_valid(r.get_data(as_text=True), SECRET)


def test_post_without_token_rejected(app):
    r = app.test_client().post("/_csrf_probe")
    assert r.status_code == 400
    assert b"CSRF" in r.data


def test_post_with_form_field_accepted(app):
    c = app.test_client()
    tok = _token(c)
    r = c.post("/_csrf_probe", data={"_csrf": tok})
    assert r.status_code == 200
    assert r.data == b"ok"


def test_post_with_header_accepted(app):
    c = app.test_client()
    tok = _token(c)
    r = c.post("/_csrf_probe", headers={"X-CSRF-Token": tok})
    assert r.status_code == 200


def test_post_with_mismatched_but_valid_token_rejected(app):
    c = app.test_client()
    _token(c)  # establishes the cookie
    other = make_csrf_token(SECRET)  # valid signature, different nonce
    r = c.post("/_csrf_probe", data={"_csrf": other})
    assert r.status_code == 400


def test_get_not_enforced(app):
    # No cookie, GET still 200 (safe method skipped by enforcement).
    assert app.test_client().get("/_csrf_probe").status_code == 200


def test_unsubscribe_endpoint_is_csrf_exempt(app, monkeypatch):
    # RFC 8058 one-click POST carries no token; must not be CSRF-rejected.
    monkeypatch.setattr("app.routes.account.query", lambda *a, **k: None)
    r = app.test_client().post("/account/unsubscribe/" + "z" * 24)
    assert r.status_code != 400
    # Match the rejection message specifically, not the bare token "CSRF":
    # base.html embeds the literal "X-CSRF-Token" header name in its JS, so
    # any page that renders the base template legitimately contains "CSRF".
    assert b"CSRF validation failed" not in r.data
