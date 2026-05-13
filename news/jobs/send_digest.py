#!/usr/bin/env python3
"""Send a once-per-day personalized email digest to each opted-in user.

Cron entry (noon UTC = pre-morning US/Asia):
  0 12 * * *  ... python send_digest.py >> .../logs/cron.log 2>&1

Settings live on the users table:
  digest_enabled      TINYINT(1) — opt-in toggle
  digest_unsub_token  CHAR(40)   — token in the unsubscribe link
  digest_last_sent_at DATETIME   — guards against double-send if cron stutters

SMTP defaults to localhost:25 (cPanel's local MTA). Set SMTP_HOST/_USER/_PASSWORD
+ SMTP_USE_TLS=1 to relay through a real SMTP provider for deliverability.
"""
import os
import smtplib
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _bootstrap import Config, get_conn, setup_logging, db_log, job_lock, AlreadyRunning

from app.ranking import build_score_sql, build_filters_sql, default_weights, parse_weights_json

JOB = "send_digest"
logger = setup_logging(JOB)


def _load_users_due(conn, guard_hours):
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, email, digest_unsub_token
               FROM users
               WHERE digest_enabled = 1
                 AND (digest_last_sent_at IS NULL
                      OR digest_last_sent_at < UTC_TIMESTAMP() - INTERVAL %s HOUR)""",
            (guard_hours,),
        )
        return cur.fetchall()


def _active_weights(conn, user_id):
    with conn.cursor() as cur:
        cur.execute(
            """SELECT weights_json FROM user_algorithms
               WHERE user_id = %s AND is_active = 1
               ORDER BY updated_at DESC LIMIT 1""",
            (user_id,),
        )
        row = cur.fetchone()
    if not row:
        return default_weights()
    return parse_weights_json(row["weights_json"])


def select_articles(conn, weights, *, lookback_hours, limit):
    """Run the same ranking SQL the feed uses, scoped to the digest window."""
    score_expr, score_params = build_score_sql(weights)
    filter_sql, filter_params = build_filters_sql(weights)
    sql = f"""
      SELECT a.id, a.title, a.summary, a.url, a.byline, a.published_at,
             s.name AS source_name, f.category,
             ({score_expr}) AS score
      FROM articles a
      JOIN sources s ON s.id = a.source_id
      JOIN article_features f ON f.article_id = a.id
      WHERE a.status = 'classified'
        AND a.published_at >= UTC_TIMESTAMP() - INTERVAL %(lookback_hours)s HOUR
        {filter_sql}
      ORDER BY score DESC, a.published_at DESC
      LIMIT %(limit)s
    """
    params = {
        **score_params,
        **filter_params,
        "lookback_hours": lookback_hours,
        "limit": limit,
    }
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _build_jinja_env():
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    templates_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "templates")
    return Environment(
        loader=FileSystemLoader(templates_dir),
        autoescape=select_autoescape(["html"]),
    )


def render_digest(env, user_email, articles, unsub_token, cfg):
    site_url = cfg.SITE_URL
    unsubscribe_url = f"{site_url}/account/unsubscribe/{unsub_token}"
    digest_date = datetime.utcnow().strftime("%a %b %-d")
    subject = f"sauce.ai/news — {len(articles)} stories for {digest_date}"

    ctx = {
        "subject": subject,
        "articles": articles,
        "digest_date": digest_date,
        "site_url": site_url,
        "unsubscribe_url": unsubscribe_url,
    }
    html = env.get_template("digest_email.html").render(**ctx)
    text = env.get_template("digest_email.txt").render(**ctx)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr(("sauce.ai/news", cfg.SMTP_FROM))
    msg["To"] = user_email
    msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    return msg


def smtp_send(cfg, from_addr, to_addr, msg):
    """Open an SMTP connection per send. Plain on port 25, STARTTLS optional."""
    smtp = smtplib.SMTP(cfg.SMTP_HOST, cfg.SMTP_PORT, timeout=30)
    try:
        smtp.ehlo()
        if cfg.SMTP_USE_TLS:
            smtp.starttls()
            smtp.ehlo()
        if cfg.SMTP_USER:
            smtp.login(cfg.SMTP_USER, cfg.SMTP_PASSWORD)
        smtp.sendmail(from_addr, [to_addr], msg.as_string())
    finally:
        try:
            smtp.quit()
        except Exception:
            pass


def main():
    try:
        with job_lock(JOB):
            _run()
    except AlreadyRunning:
        logger.info("%s lock held by another process; skipping this tick", JOB)


def _run():
    cfg = Config
    conn = get_conn()
    env = _build_jinja_env()

    sent = 0
    skipped_empty = 0
    failed = 0
    try:
        users = _load_users_due(conn, cfg.DIGEST_RESEND_GUARD_HOURS)
        logger.info("digest candidates: %d", len(users))
        for u in users:
            try:
                weights = _active_weights(conn, u["id"])
                articles = select_articles(
                    conn, weights,
                    lookback_hours=cfg.DIGEST_LOOKBACK_HOURS,
                    limit=cfg.DIGEST_MAX_ARTICLES,
                )
                if not articles:
                    skipped_empty += 1
                    logger.info("user %s: 0 articles, skipping", u["id"])
                    continue
                msg = render_digest(env, u["email"], articles, u["digest_unsub_token"] or "", cfg)
                smtp_send(cfg, cfg.SMTP_FROM, u["email"], msg)
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE users SET digest_last_sent_at = UTC_TIMESTAMP() WHERE id = %s",
                        (u["id"],),
                    )
                conn.commit()
                sent += 1
            except Exception as e:
                failed += 1
                try:
                    conn.rollback()
                except Exception:
                    pass
                logger.exception("user %s send failed: %s", u.get("id"), e)
        msg = f"sent={sent} skipped_empty={skipped_empty} failed={failed} candidates={len(users)}"
        logger.info(msg)
        db_log(conn, JOB, "info", msg)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
