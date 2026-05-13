from flask import Blueprint, g, jsonify, request

from ..db import query, execute, get_conn

bp = Blueprint("signals", __name__)

THUMB_TYPES = {"thumb_up", "thumb_down"}
OPPOSITES = {"thumb_up": "thumb_down", "thumb_down": "thumb_up"}

DOWNS_PROMPT_THRESHOLD = 3
DOWNS_PROMPT_WINDOW_DAYS = 30


def _require_user():
    u = getattr(g, "user", None)
    if not u:
        return None
    return u


@bp.route("/<int:article_id>/<signal_type>", methods=["POST"])
def record(article_id, signal_type):
    if signal_type not in THUMB_TYPES:
        return jsonify({"error": "unsupported signal"}), 400

    u = _require_user()
    if not u:
        return jsonify({"error": "auth required"}), 401

    uid = u["id"]
    conn = get_conn()

    existing = query(
        "SELECT signal_type FROM user_signals "
        "WHERE user_id = %s AND article_id = %s AND signal_type IN ('thumb_up','thumb_down')",
        (uid, article_id),
    )
    existing_types = {r["signal_type"] for r in existing}

    new_state = signal_type
    if signal_type in existing_types:
        execute(
            "DELETE FROM user_signals WHERE user_id = %s AND article_id = %s AND signal_type = %s",
            (uid, article_id, signal_type),
        )
        new_state = None
    else:
        opp = OPPOSITES[signal_type]
        if opp in existing_types:
            execute(
                "DELETE FROM user_signals WHERE user_id = %s AND article_id = %s AND signal_type = %s",
                (uid, article_id, opp),
            )
        execute(
            "INSERT INTO user_signals (user_id, article_id, signal_type) VALUES (%s, %s, %s)",
            (uid, article_id, signal_type),
        )

    prompt = None
    if new_state == "thumb_down":
        row = query(
            """SELECT s.id AS source_id, s.name AS source_name, COUNT(*) AS n
               FROM user_signals us
               JOIN articles a ON a.id = us.article_id
               JOIN sources s ON s.id = a.source_id
               LEFT JOIN user_source_prefs usp
                 ON usp.user_id = us.user_id AND usp.source_id = s.id
               WHERE us.user_id = %s
                 AND us.signal_type = 'thumb_down'
                 AND us.created_at >= UTC_TIMESTAMP() - INTERVAL %s DAY
                 AND a.source_id = (SELECT source_id FROM articles WHERE id = %s)
                 AND usp.user_id IS NULL
               GROUP BY s.id, s.name""",
            (uid, DOWNS_PROMPT_WINDOW_DAYS, article_id),
            one=True,
        )
        if row and row["n"] >= DOWNS_PROMPT_THRESHOLD:
            prompt = {"source_id": row["source_id"], "source_name": row["source_name"], "down_count": int(row["n"])}

    conn.commit()
    return jsonify({"state": new_state, "prompt": prompt})


@bp.route("/source/<int:source_id>", methods=["POST"])
def source_pref(source_id):
    u = _require_user()
    if not u:
        return jsonify({"error": "auth required"}), 401

    action = (request.form.get("action") or (request.json or {}).get("action") or "").strip()
    if action == "hide":
        weight = 0.0
    elif action == "downweight":
        weight = 0.5
    elif action == "reset":
        weight = None
    else:
        return jsonify({"error": "unknown action"}), 400

    uid = u["id"]
    if weight is None:
        execute(
            "DELETE FROM user_source_prefs WHERE user_id = %s AND source_id = %s",
            (uid, source_id),
        )
    else:
        execute(
            """INSERT INTO user_source_prefs (user_id, source_id, weight) VALUES (%s, %s, %s)
               ON DUPLICATE KEY UPDATE weight = VALUES(weight)""",
            (uid, source_id, weight),
        )
    get_conn().commit()
    return jsonify({"action": action, "weight": weight})
