#!/usr/bin/env python3
"""Poll Reddit and Hacker News for popular URLs, match against our DB, update popularity."""
import math
import os
import sys
import time
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests

from _bootstrap import Config, get_conn, setup_logging, db_log

JOB = "popularity_poll"
logger = setup_logging(JOB)

REDDIT_SUBS = ["news", "worldnews", "politics", "technology", "science", "business"]
HN_TOP = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM = "https://hacker-news.firebaseio.com/v0/item/{}.json"


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


def _fetch_reddit():
    posts = []
    headers = {"User-Agent": "sauce.ai-news/1.0"}
    for sub in REDDIT_SUBS:
        url = f"https://www.reddit.com/r/{sub}/top.json?t=day&limit=50"
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code != 200:
                continue
            for child in r.json().get("data", {}).get("children", []):
                d = child.get("data", {})
                u = d.get("url_overridden_by_dest") or d.get("url")
                if u and not u.startswith("https://www.reddit.com"):
                    posts.append({
                        "url": u, "score": int(d.get("score", 0)),
                        "comments": int(d.get("num_comments", 0)),
                    })
            time.sleep(1)  # be polite
        except Exception as e:
            logger.warning("reddit %s failed: %s", sub, e)
    return posts


def _fetch_hn():
    posts = []
    try:
        ids = requests.get(HN_TOP, timeout=10).json()[:100]
    except Exception as e:
        logger.warning("hn top failed: %s", e)
        return posts
    for hid in ids:
        try:
            item = requests.get(HN_ITEM.format(hid), timeout=10).json()
            if not item:
                continue
            u = item.get("url")
            if u:
                posts.append({
                    "url": u, "score": int(item.get("score", 0)),
                    "comments": int(item.get("descendants", 0)),
                })
        except Exception:
            continue
    return posts


def _popularity_score(score, comments):
    """Map raw engagement to 0..1 via a log curve."""
    raw = math.log1p(score + 2 * comments) / math.log1p(2000 + 2 * 500)
    return max(0.0, min(1.0, raw))


def main():
    conn = get_conn()
    matched = 0
    try:
        url_to_id = _load_our_urls(conn)
        if not url_to_id:
            logger.info("no recent articles to match")
            return

        all_posts = []
        all_posts += [{**p, "source": "reddit"} for p in _fetch_reddit()]
        all_posts += [{**p, "source": "hn"} for p in _fetch_hn()]
        logger.info("collected %d posts from external sources", len(all_posts))

        best_for_article = {}  # article_id -> popularity score
        with conn.cursor() as cur:
            for p in all_posts:
                n = _normalize_url(p["url"])
                if not n or n not in url_to_id:
                    continue
                aid = url_to_id[n]
                pop = _popularity_score(p["score"], p["comments"])
                cur.execute(
                    """INSERT INTO popularity_signals (article_id, source, score, comments)
                       VALUES (%s, %s, %s, %s)
                       ON DUPLICATE KEY UPDATE score=VALUES(score), comments=VALUES(comments),
                       fetched_at=UTC_TIMESTAMP()""",
                    (aid, p["source"], p["score"], p["comments"]),
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
        conn.close()


if __name__ == "__main__":
    main()
