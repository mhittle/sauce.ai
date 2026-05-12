#!/usr/bin/env python3
"""Fetch a slice of active RSS sources and insert new articles as 'pending'.

Run from cron every ~15 minutes. Rotates through active feeds so each one is hit
every ~1-2 hours regardless of how many you have.
"""
import hashlib
import os
import sys
import time
import socket
from datetime import datetime
from email.utils import parsedate_to_datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import feedparser

from _bootstrap import Config, get_conn, setup_logging, db_log
from app.classifier import title_hash as compute_title_hash

JOB = "fetch_feeds"
logger = setup_logging(JOB)

socket.setdefaulttimeout(20)


def _hash_url(u: str) -> str:
    return hashlib.sha1(u.strip().encode("utf-8", "ignore")).hexdigest()


def _parse_published(entry):
    for k in ("published_parsed", "updated_parsed"):
        v = getattr(entry, k, None)
        if v:
            try:
                return datetime(*v[:6])
            except (TypeError, ValueError):
                pass
    for k in ("published", "updated"):
        v = entry.get(k) if isinstance(entry, dict) else getattr(entry, k, None)
        if v:
            try:
                return parsedate_to_datetime(v).replace(tzinfo=None)
            except Exception:
                pass
    return datetime.utcnow()


def _extract_thumbnail(entry):
    media = entry.get("media_content") if isinstance(entry, dict) else getattr(entry, "media_content", None)
    if media and isinstance(media, list) and media[0].get("url"):
        return media[0]["url"]
    encs = entry.get("enclosures") if isinstance(entry, dict) else getattr(entry, "enclosures", None)
    if encs:
        for e in encs:
            if "image" in (e.get("type") or ""):
                return e.get("href") or e.get("url")
    return None


def _extract_byline(entry):
    a = entry.get("author") if isinstance(entry, dict) else getattr(entry, "author", None)
    if a:
        return str(a)[:300]
    authors = entry.get("authors") if isinstance(entry, dict) else getattr(entry, "authors", None)
    if authors and isinstance(authors, list):
        return ", ".join(x.get("name", "") for x in authors if x.get("name"))[:300]
    return None


def fetch_one(conn, source):
    sid = source["id"]
    url = source["feed_url"]
    fresh = stale = errors = 0
    try:
        parsed = feedparser.parse(url, request_headers={"User-Agent": "sauce.ai-news/1.0"})
        if parsed.bozo and not parsed.entries:
            raise RuntimeError(f"feedparser bozo: {parsed.bozo_exception}")
    except Exception as e:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE sources SET last_fetched_at=UTC_TIMESTAMP(), last_status='error',
                   last_error=%s, error_count=error_count+1 WHERE id=%s""",
                (str(e)[:1000], sid),
            )
            # Auto-deactivate after 10 consecutive failures. The source stays
            # visible in /admin/feeds; admin can hit Refresh to retry, which
            # resets error_count + re-enables on success.
            cur.execute(
                "UPDATE sources SET is_active=0 WHERE id=%s AND error_count >= 10",
                (sid,),
            )
        conn.commit()
        return 0, 0, 1

    with conn.cursor() as cur:
        for entry in parsed.entries[:60]:
            link = entry.get("link") if isinstance(entry, dict) else getattr(entry, "link", None)
            title = entry.get("title") if isinstance(entry, dict) else getattr(entry, "title", None)
            if not link or not title:
                continue
            url_hash = _hash_url(link)
            t_hash = compute_title_hash(title)
            try:
                cur.execute(
                    """INSERT IGNORE INTO articles
                       (source_id, url, url_hash, title, title_hash, summary, thumbnail_url, byline, published_at, status)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')""",
                    (
                        sid,
                        link[:1000],
                        url_hash,
                        title[:500],
                        t_hash,
                        (entry.get("summary") if isinstance(entry, dict) else getattr(entry, "summary", "")) or "",
                        _extract_thumbnail(entry),
                        _extract_byline(entry),
                        _parse_published(entry),
                    ),
                )
                if cur.rowcount > 0:
                    fresh += 1
                else:
                    stale += 1
            except Exception as e:
                logger.warning("insert error for %s: %s", link, e)
                errors += 1

        cur.execute(
            """UPDATE sources SET last_fetched_at=UTC_TIMESTAMP(), last_status='ok',
               last_error=NULL, error_count=0 WHERE id=%s""",
            (sid,),
        )
    conn.commit()
    return fresh, stale, errors


def main():
    cfg = Config
    conn = get_conn()
    batch = cfg.FEED_FETCH_BATCH
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, feed_url FROM sources
                   WHERE is_active = 1
                     AND error_count < 10
                   ORDER BY COALESCE(last_fetched_at, '1970-01-01') ASC
                   LIMIT %s""",
                (batch,),
            )
            sources = cur.fetchall()

        total_fresh = total_stale = total_err = 0
        for s in sources:
            f, st, er = fetch_one(conn, s)
            total_fresh += f
            total_stale += st
            total_err += er

        msg = f"fetched={len(sources)} fresh={total_fresh} stale={total_stale} errors={total_err}"
        logger.info(msg)
        db_log(conn, JOB, "info", msg)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
