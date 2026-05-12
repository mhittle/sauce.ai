import os
import secrets
from datetime import datetime, timedelta
from functools import wraps

import bcrypt
from flask import g, request, redirect, url_for, abort, current_app

from .db import query, execute, get_conn

SESSION_COOKIE = "news_sid"
SESSION_TTL_DAYS = 30


def hash_password(pw: str) -> bytes:
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt(rounds=12))


def check_password(pw: str, hashed: bytes) -> bool:
    if isinstance(hashed, str):
        hashed = hashed.encode("utf-8")
    try:
        return bcrypt.checkpw(pw.encode("utf-8"), hashed)
    except ValueError:
        return False


def create_session(user_id: int) -> str:
    sid = secrets.token_hex(32)
    expires = datetime.utcnow() + timedelta(days=SESSION_TTL_DAYS)
    execute(
        "INSERT INTO sessions (sid, user_id, expires_at) VALUES (%s, %s, %s)",
        (sid, user_id, expires),
    )
    get_conn().commit()
    return sid


def destroy_session(sid: str):
    if not sid:
        return
    execute("DELETE FROM sessions WHERE sid = %s", (sid,))
    get_conn().commit()


def load_user():
    """Populate g.user from the session cookie. Called per-request."""
    g.user = None
    sid = request.cookies.get(SESSION_COOKIE)
    if not sid:
        return
    row = query(
        """SELECT u.id, u.email, u.is_admin
           FROM sessions s JOIN users u ON u.id = s.user_id
           WHERE s.sid = %s AND s.expires_at > UTC_TIMESTAMP()""",
        (sid,),
        one=True,
    )
    if row:
        g.user = row


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not getattr(g, "user", None):
            return redirect(url_for("auth.login", next=request.path))
        return fn(*a, **kw)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        u = getattr(g, "user", None)
        if not u:
            return redirect(url_for("auth.login", next=request.path))
        if not u.get("is_admin"):
            abort(403)
        return fn(*a, **kw)
    return wrapper
