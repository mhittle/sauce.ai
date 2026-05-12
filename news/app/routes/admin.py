import csv
import io
import os
import subprocess
import sys
from flask import Blueprint, render_template, request, redirect, url_for, g, jsonify, abort, current_app

from ..auth import admin_required, hash_password
from ..db import query, execute, get_conn

bp = Blueprint("admin", __name__)


@bp.route("/")
@admin_required
def index():
    feeds = query("""
        SELECT
          COUNT(*) AS total,
          SUM(is_active) AS active,
          SUM(CASE WHEN last_status = 'ok' THEN 1 ELSE 0 END) AS ok,
          SUM(CASE WHEN error_count > 0 THEN 1 ELSE 0 END) AS errored
        FROM sources
    """, one=True) or {}
    pipeline = query("""
        SELECT
          SUM(status = 'pending') AS pending,
          SUM(status = 'classified') AS classified,
          SUM(status = 'failed') AS failed,
          COUNT(*) AS total
        FROM articles
    """, one=True) or {}
    today_articles = query("""
        SELECT COUNT(*) AS n
        FROM articles
        WHERE fetched_at >= UTC_DATE()
    """, one=True) or {"n": 0}
    users = query("SELECT COUNT(*) AS n FROM users", one=True) or {"n": 0}
    clicks = query("SELECT COUNT(*) AS n FROM user_clicks WHERE ts >= UTC_DATE()", one=True) or {"n": 0}
    llm_today = query("""
        SELECT COALESCE(SUM(est_cost_usd),0) AS cost,
               COALESCE(SUM(input_tokens),0) AS inp,
               COALESCE(SUM(output_tokens),0) AS outp,
               COALESCE(SUM(articles),0) AS articles
        FROM llm_usage WHERE ts >= UTC_DATE()
    """, one=True) or {}
    llm_month = query("""
        SELECT COALESCE(SUM(est_cost_usd),0) AS cost
        FROM llm_usage WHERE ts >= UTC_TIMESTAMP() - INTERVAL 30 DAY
    """, one=True) or {"cost": 0}
    return render_template(
        "admin/index.html",
        feeds=feeds, pipeline=pipeline, today_articles=today_articles,
        users=users, clicks=clicks, llm_today=llm_today, llm_month=llm_month,
    )


@bp.route("/feeds")
@admin_required
def feeds():
    sources = query("""
        SELECT s.id, s.name, s.feed_url, s.category, s.country,
               s.source_lean, s.source_reputation,
               s.is_active, s.last_fetched_at, s.last_status, s.last_error, s.error_count,
               (SELECT AVG(f.paywall)
                FROM articles a JOIN article_features f ON f.article_id = a.id
                WHERE a.source_id = s.id
                  AND a.fetched_at >= UTC_TIMESTAMP() - INTERVAL 7 DAY) AS paywall_avg
        FROM sources s
        ORDER BY s.is_active DESC, s.error_count DESC, s.name ASC
    """)
    return render_template("admin/feeds.html", sources=sources)


@bp.route("/feeds/import", methods=["POST"])
@admin_required
def feeds_import():
    """Import seed/source_lean.csv into the sources table (idempotent upsert)."""
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    csv_path = os.path.join(here, "seed", "source_lean.csv")
    if not os.path.exists(csv_path):
        return f"seed csv not found at {csv_path}", 500
    added = updated = 0
    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            existing = query("SELECT id FROM sources WHERE feed_url = %s", (row["feed_url"],), one=True)
            if existing:
                execute(
                    """UPDATE sources SET name=%s, homepage=%s, source_lean=%s, source_reputation=%s,
                       category=%s, country=%s, region=%s WHERE id=%s""",
                    (row["name"], row.get("homepage", ""), float(row["source_lean"]),
                     float(row["source_reputation"]), row["category"], row["country"],
                     row["region"], existing["id"]),
                )
                updated += 1
            else:
                execute(
                    """INSERT INTO sources (name, feed_url, homepage, source_lean, source_reputation,
                       category, country, region, is_active)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,1)""",
                    (row["name"], row["feed_url"], row.get("homepage", ""), float(row["source_lean"]),
                     float(row["source_reputation"]), row["category"], row["country"], row["region"]),
                )
                added += 1
    get_conn().commit()
    return redirect(url_for("admin.feeds", added=added, updated=updated))


@bp.route("/feeds/<int:sid>/toggle", methods=["POST"])
@admin_required
def feeds_toggle(sid):
    execute("UPDATE sources SET is_active = 1 - is_active WHERE id = %s", (sid,))
    get_conn().commit()
    return redirect(url_for("admin.feeds"))


@bp.route("/feeds/<int:sid>/delete", methods=["POST"])
@admin_required
def feeds_delete(sid):
    execute("DELETE FROM sources WHERE id = %s", (sid,))
    get_conn().commit()
    return redirect(url_for("admin.feeds"))


@bp.route("/feeds/<int:sid>/refresh", methods=["POST"])
@admin_required
def feeds_refresh(sid):
    """Re-poll the feed URL synchronously to check liveness. On success,
    reset error_count and re-enable the source. On failure, increment
    error_count (same path as the cron worker)."""
    import socket
    import feedparser
    src = query("SELECT id, feed_url FROM sources WHERE id = %s", (sid,), one=True)
    if not src:
        return ("not found", 404)
    socket.setdefaulttimeout(15)
    try:
        parsed = feedparser.parse(
            src["feed_url"],
            request_headers={"User-Agent": "sauce.ai-news/1.0"},
        )
        if parsed.bozo and not parsed.entries:
            raise RuntimeError(f"feedparser bozo: {parsed.bozo_exception}")
        execute(
            """UPDATE sources SET last_fetched_at=UTC_TIMESTAMP(), last_status='ok',
               last_error=NULL, error_count=0, is_active=1 WHERE id=%s""",
            (sid,),
        )
    except Exception as e:
        execute(
            """UPDATE sources SET last_fetched_at=UTC_TIMESTAMP(), last_status='error',
               last_error=%s, error_count=error_count+1 WHERE id=%s""",
            (str(e)[:1000], sid),
        )
    get_conn().commit()
    return redirect(url_for("admin.feeds"))


@bp.route("/feeds/add", methods=["POST"])
@admin_required
def feeds_add():
    f = request.form
    execute(
        """INSERT INTO sources (name, feed_url, homepage, source_lean, source_reputation,
           category, country, region, is_active) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,1)
           ON DUPLICATE KEY UPDATE name=VALUES(name)""",
        (f.get("name"), f.get("feed_url"), f.get("homepage", ""),
         float(f.get("source_lean", 0)), float(f.get("source_reputation", 0.5)),
         f.get("category", "general"), f.get("country", "US"), f.get("region", "national")),
    )
    get_conn().commit()
    return redirect(url_for("admin.feeds"))


@bp.route("/users")
@admin_required
def users():
    users = query("""
        SELECT u.id, u.email, u.is_admin, u.created_at,
               (SELECT COUNT(*) FROM user_algorithms ua WHERE ua.user_id = u.id) AS algo_count,
               (SELECT COUNT(*) FROM user_clicks c WHERE c.user_id = u.id) AS click_count
        FROM users u ORDER BY u.created_at DESC
    """)
    return render_template("admin/users.html", users=users)


@bp.route("/users/<int:uid>/toggle_admin", methods=["POST"])
@admin_required
def users_toggle_admin(uid):
    if uid == g.user["id"]:
        return ("Can't demote yourself", 400)
    execute("UPDATE users SET is_admin = 1 - is_admin WHERE id = %s", (uid,))
    get_conn().commit()
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:uid>/delete", methods=["POST"])
@admin_required
def users_delete(uid):
    if uid == g.user["id"]:
        return ("Can't delete yourself", 400)
    execute("DELETE FROM users WHERE id = %s", (uid,))
    get_conn().commit()
    return redirect(url_for("admin.users"))


@bp.route("/content")
@admin_required
def content():
    by_category = query("""
        SELECT f.category, COUNT(*) AS n,
               AVG(f.political_lean) AS avg_lean,
               AVG(f.objectivity) AS avg_obj
        FROM article_features f
        JOIN articles a ON a.id = f.article_id
        WHERE a.published_at >= UTC_TIMESTAMP() - INTERVAL 7 DAY
        GROUP BY f.category ORDER BY n DESC
    """)
    by_source = query("""
        SELECT s.name, COUNT(*) AS n
        FROM articles a JOIN sources s ON s.id = a.source_id
        WHERE a.fetched_at >= UTC_TIMESTAMP() - INTERVAL 1 DAY
        GROUP BY s.id ORDER BY n DESC LIMIT 25
    """)
    lean_hist = query("""
        SELECT FLOOR(political_lean * 5)/5 AS bucket, COUNT(*) AS n
        FROM article_features f
        JOIN articles a ON a.id = f.article_id
        WHERE a.published_at >= UTC_TIMESTAMP() - INTERVAL 7 DAY
        GROUP BY bucket ORDER BY bucket
    """)
    return render_template("admin/content.html", by_category=by_category, by_source=by_source, lean_hist=lean_hist)


@bp.route("/features", methods=["GET", "POST"])
@admin_required
def features():
    if request.method == "POST":
        fk = request.form.get("feature_key")
        if fk:
            execute(
                """UPDATE feature_catalog SET label=%s, description=%s, is_active=%s, sort_order=%s
                   WHERE feature_key=%s""",
                (request.form.get("label"), request.form.get("description"),
                 1 if request.form.get("is_active") else 0,
                 int(request.form.get("sort_order", 100)), fk),
            )
            get_conn().commit()
        return redirect(url_for("admin.features"))
    rows = query("SELECT * FROM feature_catalog ORDER BY sort_order ASC")
    return render_template("admin/features.html", features=rows)


@bp.route("/traffic")
@admin_required
def traffic():
    signups = query("""
        SELECT DATE(created_at) AS d, COUNT(*) AS n
        FROM users WHERE created_at >= UTC_TIMESTAMP() - INTERVAL 30 DAY
        GROUP BY d ORDER BY d
    """)
    clicks = query("""
        SELECT DATE(ts) AS d, COUNT(*) AS n
        FROM user_clicks WHERE ts >= UTC_TIMESTAMP() - INTERVAL 30 DAY
        GROUP BY d ORDER BY d
    """)
    top_articles = query("""
        SELECT a.title, a.url, s.name AS source_name, COUNT(c.id) AS clicks
        FROM user_clicks c JOIN articles a ON a.id = c.article_id
        JOIN sources s ON s.id = a.source_id
        WHERE c.ts >= UTC_TIMESTAMP() - INTERVAL 7 DAY
        GROUP BY a.id ORDER BY clicks DESC LIMIT 20
    """)
    return render_template("admin/traffic.html", signups=signups, clicks=clicks, top_articles=top_articles)


@bp.route("/tests", methods=["GET", "POST"])
@admin_required
def tests():
    """Run the bundled pytest suite from the admin UI."""
    output = None
    success = None
    if request.method == "POST":
        here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        tests_dir = os.path.join(here, "tests")
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "--maxfail=5", tests_dir],
                capture_output=True, text=True, timeout=120, cwd=here,
            )
            output = (proc.stdout or "") + "\n" + (proc.stderr or "")
            success = proc.returncode == 0
        except subprocess.TimeoutExpired:
            output = "Test run timed out after 120s."
            success = False
        except Exception as e:
            output = f"Failed to start pytest: {e}"
            success = False
    return render_template("admin/tests.html", output=output, success=success)


@bp.route("/logs")
@admin_required
def logs():
    rows = query("""
        SELECT job, level, message, ts FROM pipeline_log
        ORDER BY id DESC LIMIT 200
    """)
    return render_template("admin/logs.html", rows=rows)
