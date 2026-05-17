#!/usr/bin/env python3
"""Poll Reddit and Hacker News for popular URLs, match against our DB, update popularity."""
import os
import sys
import time
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests

from _bootstrap import Config, get_conn, setup_logging, db_log, job_lock, AlreadyRunning
from app.classifier import popularity_score

JOB = "popularity_poll"
logger = setup_logging(JOB)

REDDIT_SUBS = ["news", "worldnews", "politics", "technology", "science", "business"]
REDDIT_BASE = "https://www.reddit.com"
HN_TOP = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM = "https://hacker-news.firebaseio.com/v0/item/{}.json"
HN_THREAD = "https://news.ycombinator.com/item?id={}"

HTTP_TIMEOUT = (5, 10)
HN_BUDGET_SECONDS = 60  # cap the per-item HN walk so it can't pile up


def _normalize_url(u):
    if not u:
        return None
    try:
        p = urlsplit(u)
        host = p.netloc.lower().lstrip("www.")
        path = p.path or "/"
        return f"{host}{path}".rstrip("/")
    except Exception:
        return None


def _load_our_urls(conn):
    """Return {normalized_url: article_id} for recent articles."""
    out = {}
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, url FROM articles
               WHERE fetched_at >= UTC_TIMESTAMP() - INTERVAL 5 DAY"""
        )
        for r in cur.fetchall():
            n = _normalize_url(r["url"])
            if n:
                out[n] = r["id"]
    return out


def _fetch_reddit(http):
    posts = []
    headers = {"User-Agent": "sauce.ai-news/1.0"}
    for sub in REDDIT_SUBS:
        url = f"https://www.reddit.com/r/{sub}/top.json?t=day&limit=50"
        try:
            r = http.get(url, headers=headers, timeout=HTTP_TIMEOUT)
            if r.status_code != 200:
                continue
            for child in r.json().get("data", {}).get("children", []):
                d = child.get("data", {})
                u = d.get("url_overridden_by_dest") or d.get("url")
                if u and not u.startswith("https://www.reddit.com"):
                    perma = d.get("permalink")
                    posts.append({
                        "url": u, "score": int(d.get("score", 0)),
                        "comments": int(d.get("num_comments", 0)),
                        "permalink": (REDDIT_BASE + perma) if perma else None,
                        "subreddit": d.get("subreddit") or sub,
                    })
            time.sleep(1)  # be polite
        except Exception as e:
            logger.warning("reddit %s failed: %s", sub, e)
    return posts


def _fetch_hn(http):
    posts = []
    start = time.time()
    try:
        ids = http.get(HN_TOP, timeout=HTTP_TIMEOUT).json()[:100]
    except Exception as e:
        logger.warning("hn top failed: %s", e)
        return posts
    for hid in ids:
        if time.time() - start >= HN_BUDGET_SECONDS:
            logger.info("hn budget (%ds) reached after %d items", HN_BUDGET_SECONDS, len(posts))
            break
        try:
            item = http.get(HN_ITEM.format(hid), timeout=HTTP_TIMEOUT).json()
            if not item:
                continue
            u = item.get("url")
            if u:
                posts.append({
                    "url": u, "score": int(item.get("score", 0)),
                    "comments": int(item.get("descendants", 0)),
                    "permalink": HN_THREAD.format(hid),
                    "subreddit": None,
                })
        except Exception:
            continue
    return posts


def _popularity_score(score, comments):
    """Thin wrapper over the shared formula (app.classifier.popularity_score)
    so popularity_poll, classify_pending seed, and the maintenance.py SQL
    reconciliation all agree."""
    return popularity_score(score, comments)


def main():
    try:
        with job_lock(JOB):
            _run()
    except AlreadyRunning:
        logger.info("%s lock held by another process; skipping this tick", JOB)


def _run():
    conn = get_conn()
    http = requests.Session()
    matched = 0
    try:
        url_to_id = _load_our_urls(conn)
        if not url_to_id:
            logger.info("no recent articles to match")
            return

        all_posts = []
        all_posts += [{**p, "source": "reddit"} for p in _fetch_reddit(http)]
        all_posts += [{**p, "source": "hn"} for p in _fetch_hn(http)]
        logger.info("collected %d posts from external sources", len(all_posts))

        # Reddit + HN fetch can take 30-60s; shared-host MySQL kills idle
        # sockets in less than that. Reconnect transparently before writes.
        conn.ping(reconnect=True)

        best_for_article = {}  # article_id -> popularity score
        with conn.cursor() as cur:
            for p in all_posts:
                n = _normalize_url(p["url"])
                if not n or n not in url_to_id:
                    continue
                aid = url_to_id[n]
                pop = _popularity_score(p["score"], p["comments"])
                cur.execute(
                    """INSERT INTO popularity_signals
                         (article_id, source, score, comments, permalink, subreddit)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       ON DUPLICATE KEY UPDATE score=VALUES(score), comments=VALUES(comments),
                       permalink=VALUES(permalink), subreddit=VALUES(subreddit),
                       fetched_at=UTC_TIMESTAMP()""",
                    (aid, p["source"], p["score"], p["comments"],
                     p.get("permalink"), p.get("subreddit")),
                )
                if pop > best_for_article.get(aid, 0):
                    best_for_article[aid] = pop
                matched += 1

            for aid, pop in best_for_article.items():
                cur.execute(
                    "UPDATE article_features SET popularity=%s WHERE article_id=%s",
                    (pop, aid),
                )
        conn.commit()

        msg = f"posts={len(all_posts)} matches={matched} articles_updated={len(best_for_article)}"
        logger.info(msg)
        db_log(conn, JOB, "info", msg)
    finally:
        http.close()
        conn.close()


if __name__ == "__main__":
    main()
