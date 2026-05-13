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
        return redirect(url_for("account.settings", saved=1))

    row = query(
        "SELECT digest_enabled, digest_last_sent_at FROM users WHERE id = %s",
        (uid,),
        one=True,
    ) or {}
    return render_template(
        "account_settings.html",
        digest_enabled=bool(row.get("digest_enabled")),
        digest_last_sent_at=row.get("digest_last_sent_at"),
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
