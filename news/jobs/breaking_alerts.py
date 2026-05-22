#!/usr/bin/env python3
"""Detect a breaking-news outlet burst and email opted-in users.

Cron entry (every 15 min):
  */15 * * * *  ... python breaking_alerts.py >> .../logs/cron.log 2>&1

Master kill-switch env BREAKING_ENABLED (default on); fast no-op when off.

Detection = outlet-burst (a story_id covered by >= BREAKING_MIN_OUTLETS
distinct outlets in the last BREAKING_WINDOW_HOURS) + a single Haiku
confirmation. Per-story dedup via the UNIQUE on
``breaking_news_alerts.story_id``. Mute suppression honors each
recipient's active-profile mute keywords. Per-user daily cap
``BREAKING_MAX_PER_DAY`` (default 3) guards against a busy news day
spamming inboxes.

Fail-closed on LLMUnavailable: don't record anything for that story so a
later tick can retry while it's still in window — an unconfirmed push is
the risk we explicitly want to avoid.

The cron also tolerates the migration not being applied yet (the two new
tables may be missing post-deploy-pre-migration). All table reads are
try/except'd so a missing table yields a clean no-op, not a crash.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _bootstrap import Config, get_conn, setup_logging, db_log, job_lock, AlreadyRunning

from app import breaking
from app.classifier.llm import LLMUnavailable, _estimate_cost
from app.mailer import build_message, smtp_send
from app.term_prefs import normalize_term

JOB = "breaking_alerts"
logger = setup_logging(JOB)


SYSTEM_PROMPT = (
    "You are a news editor confirming whether a story is a 'major "
    "breaking news event' worth pushing to readers' inboxes immediately.\n\n"
    "Major events include: armed conflicts breaking out, major terror or "
    "mass-casualty attacks, large natural disasters, deaths of heads of "
    "state or globally-significant figures, election results of national "
    "significance, supreme/high court rulings of national significance, "
    "major regulatory or central-bank announcements, large-scale corporate "
    "failures.\n\n"
    "NOT major: routine political news, scheduled product launches, "
    "opinion pieces, regular-season sports, gossip, paywalled analysis, "
    "stories already widely covered earlier today, listicles.\n\n"
    "Return STRICT JSON, no surrounding prose:\n"
    "{\"is_major\": true|false, \"headline\": \"<short factual headline, "
    "no clickbait>\", \"blurb\": \"<one sentence, <= 50 words, plainly "
    "describing what happened>\"}"
)


def _llm_judge_event(cfg, title, summary, member_titles):
    """Run Haiku once for the confirmation gate.

    Returns ``(verdict_dict or None, usage_dict)``. Raises
    ``LLMUnavailable`` on any Anthropic-side failure so the caller can
    fail-closed (no record, retry next tick).
    """
    try:
        import anthropic
    except ImportError as e:
        raise LLMUnavailable(f"anthropic SDK not installed: {e}")
    if not cfg.ANTHROPIC_API_KEY:
        raise LLMUnavailable("ANTHROPIC_API_KEY not configured")

    user_block = f"Canonical headline: {title}\n\nSummary: {summary or '(none)'}\n"
    if member_titles:
        user_block += "\nOther outlets covering this:\n"
        for t in member_titles[:6]:
            user_block += f"- {t}\n"

    client = anthropic.Anthropic(api_key=cfg.ANTHROPIC_API_KEY)
    try:
        resp = client.messages.create(
            model=cfg.ANTHROPIC_MODEL,
            max_tokens=300,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_block}],
            timeout=30.0,
        )
    except Exception as e:
        raise LLMUnavailable(f"Anthropic API error: {e}")

    text = ""
    for block in resp.content:
        if getattr(block, "type", None) == "text":
            text += block.text

    usage = {
        "model": cfg.ANTHROPIC_MODEL,
        "input_tokens": getattr(resp.usage, "input_tokens", 0),
        "output_tokens": getattr(resp.usage, "output_tokens", 0),
        "cache_read_tokens": getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
        "est_cost_usd": _estimate_cost(resp.usage),
    }
    verdict = breaking.parse_llm_verdict(text)
    return verdict, usage


def _build_jinja_env():
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    templates_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "templates"
    )
    return Environment(
        loader=FileSystemLoader(templates_dir),
        autoescape=select_autoescape(["html"]),
    )


def render_alert(env, user_email, *, headline, blurb, outlet_count, story_id, unsub_token, cfg):
    """Render the one-event push email. Mirrors send_digest.render_digest's shape."""
    site_url = cfg.SITE_URL
    story_url = f"{site_url}/story/{story_id}"
    unsubscribe_url = f"{site_url}/account/alerts/unsubscribe/{unsub_token}"
    subject = f"Breaking: {headline}"

    ctx = {
        "subject": subject,
        "headline": headline,
        "blurb": blurb,
        "outlet_count": outlet_count,
        "story_url": story_url,
        "site_url": site_url,
        "unsubscribe_url": unsubscribe_url,
    }
    html = env.get_template("breaking_email.html").render(**ctx)
    text = env.get_template("breaking_email.txt").render(**ctx)

    return build_message(
        subject=subject,
        from_addr=cfg.SMTP_FROM,
        from_name="sauce.ai/news",
        to_addr=user_email,
        html=html,
        text=text,
        list_unsubscribe_url=unsubscribe_url,
    )


def _candidate_query(conn, window_hours, min_outlets):
    sql = """
        SELECT a.story_id,
               COUNT(DISTINCT a.source_id) AS outlet_count,
               MAX(a.published_at)         AS latest
        FROM articles a
        JOIN sources s ON s.id = a.source_id
        WHERE a.story_id IS NOT NULL
          AND a.published_at >= UTC_TIMESTAMP() - INTERVAL %s HOUR
          AND s.owner_id IS NULL
        GROUP BY a.story_id
        HAVING outlet_count >= %s
        ORDER BY outlet_count DESC
    """
    with conn.cursor() as cur:
        cur.execute(sql, (window_hours, min_outlets))
        return list(cur.fetchall() or ())


def _seen_story_ids(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT story_id FROM breaking_news_alerts")
        return {r["story_id"] for r in (cur.fetchall() or ())}


def _canonical_article(conn, story_id):
    with conn.cursor() as cur:
        cur.execute(
            """SELECT title, summary FROM articles
               WHERE id = %s AND story_id = %s LIMIT 1""",
            (story_id, story_id),
        )
        canon = cur.fetchone()
        cur.execute(
            """SELECT title FROM articles
               WHERE story_id = %s AND id <> %s
               ORDER BY published_at DESC LIMIT 5""",
            (story_id, story_id),
        )
        member_titles = [r["title"] for r in (cur.fetchall() or ())]
    if not canon:
        return None, []
    return canon, member_titles


def _opted_in_users(conn):
    with conn.cursor() as cur:
        cur.execute(
            """SELECT u.id, u.email, p.unsub_token, p.alerts_day, p.alerts_today
               FROM users u
               JOIN user_alert_prefs p ON p.user_id = u.id
               WHERE p.breaking_enabled = 1
                 AND p.unsub_token <> ''"""
        )
        return list(cur.fetchall() or ())


def _active_mute_terms(conn, user_id):
    with conn.cursor() as cur:
        cur.execute(
            """SELECT t.term FROM algorithm_term_prefs t
               JOIN user_algorithms ua ON ua.id = t.algorithm_id
               WHERE ua.user_id = %s AND ua.is_active = 1 AND t.mode = 'mute'""",
            (user_id,),
        )
        out = []
        for r in (cur.fetchall() or ()):
            term = normalize_term(r["term"])
            if term:
                out.append(term)
        return out


def _bump_user_alert_counter(conn, user_id, today):
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE user_alert_prefs
               SET alerts_today = CASE WHEN alerts_day = %s THEN alerts_today + 1 ELSE 1 END,
                   alerts_day = %s,
                   last_alert_at = UTC_TIMESTAMP()
               WHERE user_id = %s""",
            (today, today, user_id),
        )


def _record_llm_usage(conn, usage):
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO llm_usage (model, input_tokens, output_tokens,
                   cache_read_tokens, articles, est_cost_usd)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (usage.get("model"), usage.get("input_tokens", 0),
                 usage.get("output_tokens", 0), usage.get("cache_read_tokens", 0),
                 1, usage.get("est_cost_usd", 0.0)),
            )
    except Exception:
        pass


def _record_alert(conn, story_id, outlet_count, status, headline, blurb, recipients):
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT IGNORE INTO breaking_news_alerts
                   (story_id, outlet_count, status, headline, blurb, recipients)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (story_id, int(outlet_count), status,
                 (headline or "")[:200], (blurb or "")[:500], int(recipients)),
            )
        conn.commit()
    except Exception as e:
        logger.exception("recording %s story %s: %s", status, story_id, e)


def main():
    cfg = Config
    if not getattr(cfg, "BREAKING_ENABLED", True):
        logger.info("BREAKING_ENABLED=0; exiting no-op")
        return
    try:
        with job_lock(JOB):
            _run()
    except AlreadyRunning:
        logger.info("%s lock held by another process; skipping this tick", JOB)


def _run():
    cfg = Config
    conn = get_conn()
    env = _build_jinja_env()
    today = datetime.utcnow().date()

    candidates_total = 0
    judged = 0
    sent_events = 0
    rejected = 0
    skipped_llm = 0
    emails_sent = 0
    cost = 0.0
    try:
        # Tables may be missing pre-migration; cron must no-op rather than crash.
        try:
            candidates = _candidate_query(conn, cfg.BREAKING_WINDOW_HOURS, cfg.BREAKING_MIN_OUTLETS)
        except Exception as e:
            logger.exception("candidate query failed: %s", e)
            return
        candidates_total = len(candidates)
        if not candidates:
            logger.info("candidates=0")
            return

        try:
            seen = _seen_story_ids(conn)
        except Exception as e:
            logger.exception("breaking_news_alerts SELECT failed (migration not applied?): %s", e)
            return

        new_candidates = [c for c in candidates if c["story_id"] not in seen]
        if not new_candidates:
            logger.info("candidates=%d new=0", candidates_total)
            return

        try:
            opted_in = _opted_in_users(conn)
        except Exception as e:
            logger.exception("loading opted-in users failed (migration not applied?): %s", e)
            return

        mute_cache: dict[int, list[str]] = {}
        user_state: dict[int, dict] = {
            u["id"]: {
                "alerts_day": u.get("alerts_day"),
                "alerts_today": u.get("alerts_today") or 0,
            }
            for u in opted_in
        }

        # Idle gap before LLM / SMTP block — same lesson as BUG-009.
        conn.ping(reconnect=True)

        for cand in new_candidates:
            story_id = cand["story_id"]
            outlet_count = int(cand["outlet_count"])
            canon, member_titles = _canonical_article(conn, story_id)
            if not canon:
                continue

            judged += 1
            try:
                verdict, usage = _llm_judge_event(
                    cfg, canon["title"], canon.get("summary"), member_titles
                )
            except LLMUnavailable as e:
                skipped_llm += 1
                logger.warning("LLM unavailable for story %s: %s", story_id, e)
                continue

            if usage:
                cost += float(usage.get("est_cost_usd", 0.0) or 0.0)
                _record_llm_usage(conn, usage)

            if not verdict or not verdict["is_major"]:
                _record_alert(
                    conn, story_id, outlet_count, "rejected",
                    (verdict or {}).get("headline", ""),
                    (verdict or {}).get("blurb", ""),
                    recipients=0,
                )
                rejected += 1
                continue

            headline = verdict["headline"] or canon["title"]
            blurb = verdict["blurb"] or (canon.get("summary") or "")[:500]

            recipients_count = 0
            for u in opted_in:
                uid = u["id"]
                if uid not in mute_cache:
                    try:
                        mute_cache[uid] = _active_mute_terms(conn, uid)
                    except Exception:
                        mute_cache[uid] = []
                if breaking.is_suppressed(headline, mute_cache[uid]):
                    continue
                if not breaking.daily_cap_ok(user_state[uid], cfg.BREAKING_MAX_PER_DAY, today):
                    continue
                try:
                    msg = render_alert(
                        env, u["email"],
                        headline=headline, blurb=blurb,
                        outlet_count=outlet_count, story_id=story_id,
                        unsub_token=u["unsub_token"], cfg=cfg,
                    )
                    smtp_send(cfg, cfg.SMTP_FROM, u["email"], msg)
                except Exception as e:
                    logger.exception("user %s send failed: %s", uid, e)
                    continue
                try:
                    _bump_user_alert_counter(conn, uid, today)
                    conn.commit()
                except Exception as e:
                    logger.exception("user %s counter bump failed: %s", uid, e)
                state = user_state[uid]
                if state["alerts_day"] == today:
                    state["alerts_today"] = (state["alerts_today"] or 0) + 1
                else:
                    state["alerts_day"] = today
                    state["alerts_today"] = 1
                recipients_count += 1
                emails_sent += 1

            _record_alert(conn, story_id, outlet_count, "sent", headline, blurb, recipients_count)
            sent_events += 1

        msg = (
            f"candidates={candidates_total} judged={judged} sent_events={sent_events} "
            f"rejected={rejected} skipped_llm={skipped_llm} emails_sent={emails_sent} "
            f"llm_cost_usd={cost:.5f}"
        )
        logger.info(msg)
        db_log(conn, JOB, "info", msg)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
