"""Hand-rolled CSRF protection (signed double-submit cookie).

Zero new dependencies — stdlib `hmac`/`hashlib`/`secrets` only. Chosen over
Flask-WTF because adding a dependency means another manual `pip install` on
the cPanel host (the "Run Pip Install" button is greyed out there) and a
`requirements.txt` merge conflict with in-flight work.

Token shape: ``<nonce>.<hexsig>`` where ``hexsig = HMAC-SHA256(SECRET_KEY,
nonce)``. The signature binds the token to the app secret, so an attacker
who can only set a cookie on the victim (cookie-injection) still can't forge
a token that passes verification. The same signed value is stored in the
``news_csrf`` cookie and must be echoed back in the ``_csrf`` form field or
the ``X-CSRF-Token`` header; the two are compared in constant time
(classic double-submit), and the signature is verified on top of that.

The pure helpers (`make_csrf_token`, `csrf_token_valid`, `tokens_match`)
import no Flask so they stay unit-testable without the framework, matching
the convention of `app/language.py` / `app/discovery.py`.
"""

import hashlib
import hmac
import secrets

CSRF_COOKIE = "news_csrf"
CSRF_FORM_FIELD = "_csrf"
CSRF_HEADER = "X-CSRF-Token"

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Endpoints that must NOT be CSRF-enforced.
# - `account.unsubscribe` is the RFC 8058 one-click List-Unsubscribe-Post
#   target: mail clients POST to it with no token and no session, and it's
#   already authenticated by the unguessable 40-hex digest token in the
#   URL, so it's CSRF-resistant by construction.
# - `lab.vote` is the anonymous vote endpoint for the root-domain
#   lab landing page (`https://sauce.ai/`). The static page can't carry
#   the news app's CSRF cookie (different rendering path), and the
#   endpoint is anon-only with a per-voter UNIQUE index — a forged vote
#   on someone else's behalf just flips one anonymous concept vote.
# - The `agent_ops.*` endpoints are the HMAC-authenticated prod-ops
#   executor (Phase 4). They carry no session cookie and are
#   authenticated by an HMAC-SHA256 signature over the request body
#   (keyed by AGENT_OPS_SECRET) with a freshness window — a far
#   stronger guarantee than the double-submit cookie, which a machine
#   caller can't carry anyway.
_EXEMPT_ENDPOINTS = frozenset({
    "account.unsubscribe",
    "lab.vote",
    "agent_ops.run_migration",
    "agent_ops.restart_app",
    "agent_ops.verify_schema",
    "agent_ops.report_run",
})


def _sign(secret: str, nonce: str) -> str:
    return hmac.new(secret.encode("utf-8"), nonce.encode("utf-8"), hashlib.sha256).hexdigest()


def make_csrf_token(secret: str) -> str:
    nonce = secrets.token_urlsafe(32)
    return f"{nonce}.{_sign(secret, nonce)}"


def csrf_token_valid(token: str, secret: str) -> bool:
    if not token or "." not in token:
        return False
    nonce, _, sig = token.partition(".")
    if not nonce or not sig:
        return False
    return hmac.compare_digest(sig, _sign(secret, nonce))


def tokens_match(a: str, b: str) -> bool:
    if not a or not b:
        return False
    return hmac.compare_digest(a, b)


def init_csrf(app):
    """Wire CSRF resolution, enforcement, cookie emission, and the
    ``csrf_token`` / ``csrf_field`` template helpers into a Flask app."""
    from flask import g, request
    from markupsafe import Markup

    @app.before_request
    def _csrf_protect():
        secret = app.config["SECRET_KEY"]
        cookie_token = request.cookies.get(CSRF_COOKIE)

        if cookie_token and csrf_token_valid(cookie_token, secret):
            g.csrf_token = cookie_token
        else:
            g.csrf_token = make_csrf_token(secret)
            g._csrf_set_cookie = True

        if not app.config.get("CSRF_ENABLED", True):
            return
        if request.method not in _UNSAFE_METHODS:
            return
        if request.endpoint in _EXEMPT_ENDPOINTS:
            return

        submitted = request.form.get(CSRF_FORM_FIELD) or request.headers.get(CSRF_HEADER)
        if (
            not cookie_token
            or not csrf_token_valid(cookie_token, secret)
            or not tokens_match(submitted, cookie_token)
        ):
            return ("CSRF validation failed. Reload the page and try again.", 400)

    @app.after_request
    def _csrf_set_cookie(resp):
        if g.get("_csrf_set_cookie") and g.get("csrf_token"):
            resp.set_cookie(
                CSRF_COOKIE,
                g.csrf_token,
                max_age=30 * 86400,
                httponly=True,
                samesite="Lax",
                secure=request.is_secure,
            )
        return resp

    @app.context_processor
    def _csrf_context():
        token = g.get("csrf_token", "")

        def csrf_field():
            return Markup(
                '<input type="hidden" name="%s" value="%s">' % (CSRF_FORM_FIELD, token)
            )

        return {"csrf_token": token, "csrf_field": csrf_field}
