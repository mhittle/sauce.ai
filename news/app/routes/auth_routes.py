from flask import Blueprint, request, render_template, redirect, url_for, make_response, g, flash, current_app
from ..auth import (
    SESSION_COOKIE, SESSION_TTL_DAYS,
    hash_password, check_password,
    create_session, destroy_session,
)
from ..ratelimit import client_ip
from ..db import query, execute, get_conn

bp = Blueprint("auth", __name__)


def _safe_next(target):
    if not target or not target.startswith("/"):
        return None
    return target


def _rate_limited():
    """True if this client IP has exceeded the auth attempt window."""
    limiter = current_app.extensions["auth_limiter"]
    return not limiter.hit(client_ip(request))


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        if _rate_limited():
            return render_template(
                "signup.html", error="Too many attempts. Wait a few minutes and try again."
            ), 429
        email = (request.form.get("email") or "").strip().lower()
        pw = request.form.get("password") or ""
        if not email or "@" not in email or len(pw) < 8:
            return render_template("signup.html", error="Need a valid email and 8+ char password."), 400
        existing = query("SELECT id FROM users WHERE email = %s", (email,), one=True)
        if existing:
            return render_template("signup.html", error="That email is already registered."), 400
        uid = execute("INSERT INTO users (email, password_hash) VALUES (%s, %s)", (email, hash_password(pw)))
        get_conn().commit()
        sid = create_session(uid)
        resp = make_response(redirect(url_for("algo.index")))
        resp.set_cookie(SESSION_COOKIE, sid, max_age=SESSION_TTL_DAYS * 86400, httponly=True, samesite="Lax")
        return resp
    return render_template("signup.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    nxt = _safe_next(request.args.get("next") or request.form.get("next"))
    if request.method == "POST":
        if _rate_limited():
            return render_template(
                "login.html", error="Too many attempts. Wait a few minutes and try again.", next=nxt
            ), 429
        email = (request.form.get("email") or "").strip().lower()
        pw = request.form.get("password") or ""
        row = query("SELECT id, password_hash FROM users WHERE email = %s", (email,), one=True)
        if not row or not check_password(pw, row["password_hash"]):
            return render_template("login.html", error="Invalid email or password.", next=nxt), 400
        sid = create_session(row["id"])
        resp = make_response(redirect(nxt or url_for("feed.index")))
        resp.set_cookie(SESSION_COOKIE, sid, max_age=SESSION_TTL_DAYS * 86400, httponly=True, samesite="Lax")
        return resp
    return render_template("login.html", next=nxt)


@bp.route("/logout", methods=["POST", "GET"])
def logout():
    sid = request.cookies.get(SESSION_COOKIE)
    destroy_session(sid)
    resp = make_response(redirect(url_for("feed.index")))
    resp.delete_cookie(SESSION_COOKIE)
    return resp
