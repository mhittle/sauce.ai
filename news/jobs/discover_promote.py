#!/usr/bin/env python3
"""Nightly RSS auto-discovery + validation for pending candidates.

Selects `candidate_sources` rows that are still `pending` and whose
score has crossed the promotion threshold (Config.DISCOVER_PROMOTION_SCORE_MIN),
or that have a feed_url already (LLM-suggested rows arrive pre-loaded),
or that were validated more than DISCOVER_PROMOTE_REVALIDATE_DAYS ago.

For each, tries `app.discovery.discover_feed_url(domain)`:
- success → `state='validated'`, `feed_url`/`name`/`homepage_url` filled,
  awaiting admin approval on /admin/discovery
- failure → `state='rejected'`, `reject_reason='no feed discovered'`

HTTP work runs in a ThreadPoolExecutor (configurable workers) to keep
within the wallclock budget on the shared host. Each per-candidate
failure is contained — one slow domain can't kill the batch.
"""
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests
from requests.adapters import HTTPAdapter

from _bootstrap import Config, get_conn, setup_logging, db_log, job_lock, AlreadyRunning
from app.discovery import discover_feed_url, try_feed_url

JOB = "discover_promote"
logger = setup_logging(JOB)


def _make_session(pool=20):
    s = requests.Session()
    adapter = HTTPAdapter(pool_connections=pool, pool_maxsize=pool)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


def _load_candidates(conn, score_min, batch_limit, revalidate_days):
    """Pull pending rows ready for a validation attempt.

    Three inclusion paths:
    1. score >= score_min and never validated
    2. feed_url already set (LLM-suggested rows arrive pre-loaded with
       a candidate URL — validate the URL directly without crawling)
    3. previously validated/rejected longer than `revalidate_days` ago
       AND still in a non-terminal state (i.e., the admin hasn't
       approved/rejected/blacklisted yet)
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, domain, feed_url
                 FROM candidate_sources
                WHERE state = 'pending'
                  AND (score >= %s OR feed_url IS NOT NULL)
                  AND (validation_attempted_at IS NULL
                       OR validation_attempted_at < UTC_TIMESTAMP() - INTERVAL %s DAY)
                ORDER BY score DESC, first_seen_at ASC
                LIMIT %s""",
            (score_min, revalidate_days, batch_limit),
        )
        return cur.fetchall()


def _validate_one(session, candidate):
    """Returns (id, result_dict_or_None, error_str_or_None)."""
    cid = candidate["id"]
    pre_feed = candidate.get("feed_url")
    try:
        if pre_feed:
            hit = try_feed_url(session, pre_feed)
            if hit:
                return cid, hit, None
        domain = candidate["domain"]
        hit = discover_feed_url(domain, session=session)
        if hit:
            return cid, hit, None
        return cid, None, "no feed discovered"
    except Exception as e:
        return cid, None, f"crawl error: {e}"[:255]


def _apply_result(conn, cid, hit, error):
    with conn.cursor() as cur:
        if hit:
            cur.execute(
                """UPDATE candidate_sources
                      SET state = 'validated',
                          feed_url = %s,
                          name = COALESCE(NULLIF(%s, ''), name),
                          homepage_url = %s,
                          validation_attempted_at = UTC_TIMESTAMP(),
                          validation_error = NULL
                    WHERE id = %s""",
                (hit["feed_url"][:1024], hit["name"][:200], hit["homepage"][:1024], cid),
            )
        else:
            cur.execute(
                """UPDATE candidate_sources
                      SET state = 'rejected',
                          reject_reason = 'no feed discovered',
                          validation_attempted_at = UTC_TIMESTAMP(),
                          validation_error = %s
                    WHERE id = %s""",
                ((error or "")[:255], cid),
            )


def main():
    try:
        with job_lock(JOB):
            _run()
    except AlreadyRunning:
        logger.info("%s lock held by another process; skipping this tick", JOB)


def _run():
    conn = get_conn()
    session = _make_session(pool=max(Config.DISCOVER_PROMOTE_WORKERS * 2, 20))
    validated = rejected = 0
    start = time.time()
    try:
        candidates = _load_candidates(
            conn,
            Config.DISCOVER_PROMOTION_SCORE_MIN,
            Config.DISCOVER_PROMOTE_BATCH_LIMIT,
            Config.DISCOVER_PROMOTE_REVALIDATE_DAYS,
        )
        if not candidates:
            logger.info("no candidates ready for validation")
            return

        results: list[tuple[int, dict | None, str | None]] = []
        with ThreadPoolExecutor(max_workers=Config.DISCOVER_PROMOTE_WORKERS) as pool:
            futures = {
                pool.submit(_validate_one, session, c): c["id"]
                for c in candidates
            }
            for fut in as_completed(futures):
                if time.time() - start >= Config.DISCOVER_PROMOTE_BUDGET_SECONDS:
                    logger.info(
                        "wallclock budget %ds reached; flushing %d results so far",
                        Config.DISCOVER_PROMOTE_BUDGET_SECONDS, len(results),
                    )
                    break
                try:
                    results.append(fut.result())
                except Exception as e:
                    cid = futures[fut]
                    logger.warning("candidate %s future raised: %s", cid, e)

        conn.ping(reconnect=True)
        for cid, hit, err in results:
            _apply_result(conn, cid, hit, err)
            if hit:
                validated += 1
            else:
                rejected += 1
        conn.commit()

        msg = (
            f"candidates={len(candidates)} validated={validated} "
            f"rejected={rejected} secs={int(time.time() - start)}"
        )
        logger.info(msg)
        db_log(conn, JOB, "info", msg)
    finally:
        session.close()
        conn.close()


if __name__ == "__main__":
    main()
