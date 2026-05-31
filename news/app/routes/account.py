import secrets

from flask import Blueprint, render_template, request, g, redirect, url_for

from ..auth import login_required
from ..db import query, execute, get_conn

bp = Blueprint("account", __name__)


def _ensure_unsub_token(user_id):
    row = query("SELECT digest_unsub_token FROM users WHERE id = %s", (user_id,), one=True)
    token = (row or {}).get("digest_unsub_token") or ""
    if not token:
        token = secrets.token_hex(20)
        execute("UPDATE users SET digest_unsub_token = %s WHERE id = %s", (token, user_id))
        get_conn().commit()
    return token


def _ensure_alert_prefs_token(user_id):
    """Ensure a `user_alert_prefs` row + non-empty `unsub_token` exist for
    this user. Returns the token. Tolerates the table not yet existing
    (returns "" so settings() degrades to "off"); BUG-007 safe per spec."""
    try:
        row = query(
            "SELECT unsub_token FROM user_alert_prefs WHERE user_id = %s",
            (user_id,),
            one=True,
        )
    except Exception:
        return ""
    if row is None:
        token = secrets.token_hex(20)
        try:
            execute(
                "INSERT INTO user_alert_prefs (user_id, unsub_token) VALUES (%s, %s)",
                (user_id, token),
            )
            get_conn().commit()
        except Exception:
            return ""
        return token
    token = row.get("unsub_token") or ""
    if not token:
        token = secrets.token_hex(20)
        try:
            execute(
                "UPDATE user_alert_prefs SET unsub_token = %s WHERE user_id = %s",
                (token, user_id),
            )
            get_conn().commit()
        except Exception:
            return ""
    return token


@bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    uid = g.user["id"]
    if request.method == "POST":
        enable = request.form.get("digest_enabled") == "on"
        if enable:
            _ensure_unsub_token(uid)
        execute("UPDATE users SET digest_enabled = %s WHERE id = %s", (1 if enable else 0, uid))
        get_conn().commit()

        # Breaking-news alerts: independent of the digest. Tolerate the
        # user_alert_prefs migration not having been applied yet.
        breaking_on = request.form.get("breaking_enabled") == "on"
        if breaking_on:
            _ensure_alert_prefs_token(uid)
        try:
            execute(
                """INSERT INTO user_alert_prefs (user_id, breaking_enabled)
                   VALUES (%s, %s)
                   ON DUPLICATE KEY UPDATE breaking_enabled = VALUES(breaking_enabled)""",
                (uid, 1 if breaking_on else 0),
            )
            get_conn().commit()
        except Exception:
            pass
        return redirect(url_for("account.settings", saved=1))

    row = query(
        "SELECT digest_enabled, digest_last_sent_at FROM users WHERE id = %s",
        (uid,),
        one=True,
    ) or {}
    try:
        alert_row = query(
            "SELECT breaking_enabled, last_alert_at FROM user_alert_prefs WHERE user_id = %s",
            (uid,),
            one=True,
        ) or {}
    except Exception:
        alert_row = {}
    return render_template(
        "account_settings.html",
        digest_enabled=bool(row.get("digest_enabled")),
        digest_last_sent_at=row.get("digest_last_sent_at"),
        breaking_enabled=bool(alert_row.get("breaking_enabled")),
        breaking_last_alert_at=alert_row.get("last_alert_at"),
        saved=bool(request.args.get("saved")),
    )


@bp.route("/unsubscribe/<token>", methods=["GET", "POST"])
def unsubscribe(token):
    if not token or len(token) < 20:
        return render_template("unsubscribed.html", ok=False), 404
    row = query(
        "SELECT id, email FROM users WHERE digest_unsub_token = %s",
        (token,),
        one=True,
    )
    if not row:
        return render_template("unsubscribed.html", ok=False), 404
    new_token = secrets.token_hex(20)
    execute(
        "UPDATE users SET digest_enabled = 0, digest_unsub_token = %s WHERE id = %s",
        (new_token, row["id"]),
    )
    get_conn().commit()
    return render_template("unsubscribed.html", ok=True, email=row["email"])


@bp.route("/alerts/unsubscribe/<token>", methods=["GET", "POST"])
def alerts_unsubscribe(token):
    """RFC 8058 one-click unsubscribe for breaking-news alerts. CSRF-exempt
    (the unguessable 40-hex token in the URL is the authenticator, same
    pattern as the digest unsubscribe)."""
    if not token or len(token) < 20:
        return render_template("unsubscribed.html", ok=False), 404
    try:
        row = query(
            "SELECT user_id FROM user_alert_prefs WHERE unsub_token = %s",
            (token,),
            one=True,
        )
    except Exception:
        # Migration not applied yet: surface as already-unsubscribed so
        # the link a user clicked from an email never 500s on them.
        return render_template("unsubscribed.html", ok=True, email="")
    if not row:
        return render_template("unsubscribed.html", ok=False), 404
    new_token = secrets.token_hex(20)
    execute(
        "UPDATE user_alert_prefs SET breaking_enabled = 0, unsub_token = %s WHERE user_id = %s",
        (new_token, row["user_id"]),
    )
    get_conn().commit()
    user = query("SELECT email FROM users WHERE id = %s", (row["user_id"],), one=True) or {}
    return render_template("unsubscribed.html", ok=True, email=user.get("email") or "")
