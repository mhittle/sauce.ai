#!/usr/bin/env python3
"""Hourly source-discovery harvest.

Re-polls the same Reddit subs + HN top stories that `popularity_poll`
visits, then for every submitted URL whose domain isn't already in
`sources` (or already-decided in `candidate_sources`), upserts a row in
`candidate_sources` and bumps its score.

Doesn't touch `articles` or `popularity_signals` — that work belongs to
popularity_poll, which keeps its own cadence. The two jobs hit the same
external APIs at slightly different times, which is fine: Reddit/HN both
serve cached JSON.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests

from _bootstrap import Config, get_conn, setup_logging, db_log, job_lock, AlreadyRunning
from app.discovery import extract_domain

JOB = "discover_harvest"
logger = setup_logging(JOB)

REDDIT_SUBS = ["news", "worldnews", "politics", "technology", "science", "business"]
HN_TOP = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM = "https://hacker-news.firebaseio.com/v0/item/{}.json"

HTTP_TIMEOUT = (5, 10)
HN_ITEM_LIMIT = 100
HN_BUDGET_SECONDS = 60

VIA = "reddit_hn"


def _load_known_domains(conn):
    """Return the set of domains already represented in `sources`.

    sources.feed_url is the canonical key; we also fold in homepage for
    cases where the feed URL lives on a feed.bar.com subdomain.
    """
    out = set()
    with conn.cursor() as cur:
        cur.execute("SELECT feed_url, homepage FROM sources")
        for row in cur.fetchall():
            for u in (row.get("feed_url"), row.get("homepage")):
                d = extract_domain(u or "")
                if d:
                    out.add(d)
    return out


def _load_decided_domains(conn):
    """Return domains already approved / rejected / blacklisted in
    candidate_sources. We still update last_seen on `pending` and
    `validated` rows below, so those aren't excluded here."""
    out = set()
    with conn.cursor() as cur:
        cur.execute(
            """SELECT domain FROM candidate_sources
               WHERE state IN ('approved', 'rejected', 'blacklisted')"""
        )
        for row in cur.fetchall():
            out.add(row["domain"])
    return out


def _fetch_reddit_urls(http):
    headers = {"User-Agent": "sauce.ai-news/1.0"}
    urls = []
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
                    urls.append(u)
            time.sleep(1)
        except Exception as e:
            logger.warning("reddit %s failed: %s", sub, e)
    return urls


def _fetch_hn_urls(http):
    urls = []
    start = time.time()
    try:
        ids = http.get(HN_TOP, timeout=HTTP_TIMEOUT).json()[:HN_ITEM_LIMIT]
    except Exception as e:
        logger.warning("hn top failed: %s", e)
        return urls
    for hid in ids:
        if time.time() - start >= HN_BUDGET_SECONDS:
            logger.info("hn budget reached after %d items", len(urls))
            break
        try:
            item = http.get(HN_ITEM.format(hid), timeout=HTTP_TIMEOUT).json()
            if item and item.get("url"):
                urls.append(item["url"])
        except Exception:
            continue
    return urls


def _upsert_candidates(conn, domains_seen: dict, via: str):
    """domains_seen: {domain: hit_count_this_tick}."""
    upserted = 0
    if not domains_seen:
        return 0
    with conn.cursor() as cur:
        for domain, hits in domains_seen.items():
            cur.execute(
                """INSERT INTO candidate_sources
                       (domain, score, first_seen_via, last_seen_via,
                        first_seen_at, last_seen_at, state)
                   VALUES (%s, %s, %s, %s, UTC_TIMESTAMP(), UTC_TIMESTAMP(), 'pending')
                   ON DUPLICATE KEY UPDATE
                       score = score + VALUES(score),
                       last_seen_via = VALUES(last_seen_via),
                       last_seen_at = UTC_TIMESTAMP()""",
                (domain, hits, via, via),
            )
            upserted += 1
    conn.commit()
    return upserted


def harvest_urls(http):
    """Return the deduped list of URLs collected this tick. Split out
    so tests can exercise the URL handling without monkeypatching
    Reddit + HN separately."""
    all_urls = _fetch_reddit_urls(http)
    all_urls += _fetch_hn_urls(http)
    return all_urls


def count_new_domains(urls, known_domains, decided_domains):
    """Pure: take the raw URL list, return {domain: hit_count} for
    domains we don't already have."""
    out: dict[str, int] = {}
    for u in urls:
        d = extract_domain(u)
        if not d:
            continue
        if d in known_domains or d in decided_domains:
            continue
        out[d] = out.get(d, 0) + 1
    return out


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
        known = _load_known_domains(conn)
        decided = _load_decided_domains(conn)
        urls = harvest_urls(http)
        conn.ping(reconnect=True)
        new_domains = count_new_domains(urls, known, decided)
        upserted = _upsert_candidates(conn, new_domains, VIA)
        msg = (
            f"urls={len(urls)} known={len(known)} decided={len(decided)} "
            f"candidates_upserted={upserted}"
        )
        logger.info(msg)
        db_log(conn, JOB, "info", msg)
    finally:
        http.close()
        conn.close()


if __name__ == "__main__":
    main()
