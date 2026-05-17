#!/usr/bin/env python3
"""Harvest external trending topics (Google Trends + Google News RSS) and
score recent articles by how strongly they match what's trending.

Writes `article_features.trending` (0..1). The feed's "Trending" sort
orders by this then by the user's algo score, so within the hot topics
the reader still gets their best-by-algorithm articles (BUG-015).

Run from cron every ~30 min (mirrors popularity_poll cadence). The score
is recomputed for the whole rolling window each tick so yesterday's hot
topics decay out on their own — no separate reset job needed.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests

from _bootstrap import Config, get_conn, setup_logging, db_log, job_lock, AlreadyRunning
from app.trending import parse_trends_rss, parse_gnews_rss, build_topic_index, score_article

JOB = "trending_poll"
logger = setup_logging(JOB)

UA = "sauce.ai-news/1.0"
HTTP_TIMEOUT = (5, 15)

TRENDS_RSS = "https://trends.google.com/trends/trendingsearches/daily/rss?geo=US"
GNEWS_BASE = "https://news.google.com/rss"
GNEWS_CEID = "hl=en-US&gl=US&ceid=US:en"
# Top stories plus a handful of section feeds for topical breadth. Bounded
# (~6 small GETs) so a slow Google response can't blow the cron tick.
GNEWS_FEEDS = [
    f"{GNEWS_BASE}?{GNEWS_CEID}",
    f"{GNEWS_BASE}/headlines/section/topic/WORLD?{GNEWS_CEID}",
    f"{GNEWS_BASE}/headlines/section/topic/NATION?{GNEWS_CEID}",
    f"{GNEWS_BASE}/headlines/section/topic/BUSINESS?{GNEWS_CEID}",
    f"{GNEWS_BASE}/headlines/section/topic/TECHNOLOGY?{GNEWS_CEID}",
    f"{GNEWS_BASE}/headlines/section/topic/SCIENCE?{GNEWS_CEID}",
]

TRENDING_WINDOW_DAYS = int(os.environ.get("TRENDING_WINDOW_DAYS", "2"))
TRENDING_BUDGET_SECONDS = int(os.environ.get("TRENDING_BUDGET_SECONDS", "60"))


def _get(http, url):
    try:
        r = http.get(url, headers={"User-Agent": UA}, timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            logger.warning("GET %s -> HTTP %s", url, r.status_code)
            return None
        return r.content
    except Exception as e:
        logger.warning("GET %s failed: %s", url, e)
        return None


def _harvest_topics(http):
    start = time.time()
    trends = []
    body = _get(http, TRENDS_RSS)
    if body:
        try:
            trends = parse_trends_rss(body)
        except Exception as e:
            logger.warning("parse trends failed: %s", e)

    gnews = []
    for url in GNEWS_FEEDS:
        if time.time() - start >= TRENDING_BUDGET_SECONDS:
            logger.info("trending HTTP budget (%ds) reached", TRENDING_BUDGET_SECONDS)
            break
        body = _get(http, url)
        if not body:
            continue
        try:
            gnews.extend(parse_gnews_rss(body))
        except Exception as e:
            logger.warning("parse gnews %s failed: %s", url, e)
        time.sleep(0.5)  # be polite to Google
    return trends, gnews


def _load_window_articles(conn):
    with conn.cursor() as cur:
        cur.execute(
            """SELECT a.id, a.title, a.summary
               FROM articles a
               JOIN article_features f ON f.article_id = a.id
               WHERE a.status = 'classified'
                 AND a.published_at >= UTC_TIMESTAMP() - INTERVAL %s DAY""",
            (TRENDING_WINDOW_DAYS,),
        )
        return cur.fetchall()


def main():
    try:
        with job_lock(JOB):
            _run()
    except AlreadyRunning:
        logger.info("%s lock held by another process; skipping this tick", JOB)


def _run():
    conn = get_conn()
    http = requests.Session()
    try:
        trends, gnews = _harvest_topics(http)
        topics = build_topic_index(trends, gnews)
        logger.info(
            "harvested trends=%d gnews=%d -> topics=%d",
            len(trends), len(gnews), len(topics),
        )

        # RSS fan-out can outlast the shared-host MySQL idle timeout
        # (BUG-009); reconnect transparently before any writes.
        conn.ping(reconnect=True)

        rows = _load_window_articles(conn)
        if not rows:
            logger.info("no in-window articles to score")
            db_log(conn, JOB, "info", "topics=%d articles=0 matched=0" % len(topics))
            return

        updates = []
        matched = 0
        for r in rows:
            s = score_article(r["title"], r["summary"], topics) if topics else 0.0
            if s > 0:
                matched += 1
            updates.append((s, r["id"]))

        with conn.cursor() as cur:
            cur.executemany(
                "UPDATE article_features SET trending=%s WHERE article_id=%s",
                updates,
            )
        conn.commit()

        msg = (
            f"topics={len(topics)} articles={len(rows)} matched={matched} "
            f"window_days={TRENDING_WINDOW_DAYS}"
        )
        logger.info(msg)
        db_log(conn, JOB, "info", msg)
    finally:
        http.close()
        conn.close()


if __name__ == "__main__":
    main()
