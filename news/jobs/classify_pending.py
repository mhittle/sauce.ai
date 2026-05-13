#!/usr/bin/env python3
"""Classify pending articles with rules + (optional) LLM.

Run every ~5 minutes from cron. Walltime-budgeted so a stuck LLM call can't
exhaust shared-host CPU quota.
"""
import os
import sys
import time
from datetime import datetime

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _bootstrap import Config, get_conn, setup_logging, db_log, job_lock, AlreadyRunning
from app.classifier import (
    compute_rules_features, classify_batch_llm, LLMUnavailable, normalize_byline,
    source_obscurity_score, story_obscurity_score, detect_paywall,
)
from app.classifier.rules import split_bylines
from app.extractor import extract_body

JOB = "classify_pending"
logger = setup_logging(JOB)

SIMHASH_HAMMING_MAX = 8
CLUSTER_LOOKBACK_HOURS = 48


def _assign_story_id(cur, art):
    """Attach `art` to a cluster within the last CLUSTER_LOOKBACK_HOURS using
    title_hash exact-match OR simhash Hamming<=SIMHASH_HAMMING_MAX. If `art`
    has higher source_reputation than the cluster's current canonical, promote
    `art` to canonical and rewrite the cluster's story_id. Otherwise adopt
    the existing canonical's id. No-op if no match is found.
    """
    my_id = art["id"]
    my_sim = art.get("simhash")
    my_th = art.get("title_hash")
    my_rep = float(art.get("source_reputation") or 0.5)
    my_pub = art.get("published_at")

    # Find best existing candidate. Title-hash exact match wins (Hamming 0
    # effectively), then nearest simhash. ORDER prefers smaller hd, then older
    # article so deterministic.
    candidate = None
    if my_th:
        cur.execute(
            """SELECT a2.id, a2.story_id
               FROM articles a2
               WHERE a2.title_hash = %s
                 AND a2.id <> %s
                 AND a2.fetched_at >= UTC_TIMESTAMP() - INTERVAL %s HOUR
               ORDER BY a2.id ASC LIMIT 1""",
            (my_th, my_id, CLUSTER_LOOKBACK_HOURS),
        )
        candidate = cur.fetchone()
    if not candidate and my_sim is not None:
        cur.execute(
            """SELECT a2.id, a2.story_id, BIT_COUNT(a2.simhash ^ %s) AS hd
               FROM articles a2
               WHERE a2.fetched_at >= UTC_TIMESTAMP() - INTERVAL %s HOUR
                 AND a2.simhash IS NOT NULL
                 AND a2.id <> %s
                 AND BIT_COUNT(a2.simhash ^ %s) <= %s
               ORDER BY hd ASC, a2.id ASC LIMIT 1""",
            (my_sim, CLUSTER_LOOKBACK_HOURS, my_id, my_sim, SIMHASH_HAMMING_MAX),
        )
        candidate = cur.fetchone()
    if not candidate:
        return False

    existing_story_id = candidate["story_id"] or candidate["id"]

    # Look up the cluster's current canonical (the member whose id == story_id).
    cur.execute(
        """SELECT a3.id, a3.published_at, s3.source_reputation
           FROM articles a3 JOIN sources s3 ON s3.id = a3.source_id
           WHERE a3.id = %s AND a3.story_id = %s""",
        (existing_story_id, existing_story_id),
    )
    canonical = cur.fetchone()
    if not canonical:
        # The cluster's pointed-at canonical is gone (pruned). Reset by adopting
        # the candidate row's own id.
        cur.execute("UPDATE articles SET story_id=%s WHERE id=%s",
                    (candidate["id"], my_id))
        return True

    canon_rep = float(canonical["source_reputation"] or 0.5)
    canon_pub = canonical["published_at"]
    promote = (
        my_rep > canon_rep
        or (my_rep == canon_rep and my_pub is not None and canon_pub is not None
            and my_pub < canon_pub)
    )
    if promote:
        cur.execute("UPDATE articles SET story_id=%s WHERE story_id=%s",
                    (my_id, existing_story_id))
    else:
        cur.execute("UPDATE articles SET story_id=%s WHERE id=%s",
                    (existing_story_id, my_id))
    return True


def _ensure_journalist(cur, normalized, display):
    cur.execute("SELECT id FROM journalists WHERE normalized_name=%s", (normalized,))
    row = cur.fetchone()
    if row:
        return row["id"]
    cur.execute(
        "INSERT INTO journalists (normalized_name, display_name) VALUES (%s, %s)",
        (normalized, display[:200]),
    )
    return cur.lastrowid


def main():
    try:
        with job_lock(JOB):
            _run()
    except AlreadyRunning:
        logger.info("%s lock held by another process; skipping this tick", JOB)


def _run():
    cfg = Config
    start = time.time()
    conn = get_conn()
    classified_total = llm_articles = 0
    cost_total = 0.0
    http = requests.Session()
    try:
        while time.time() - start < cfg.CLASSIFY_BUDGET_SECONDS:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT a.id, a.url, a.title, a.summary, a.byline, a.title_hash,
                              a.simhash, a.published_at,
                              s.id AS source_id, s.name AS source_name,
                              s.source_lean, s.source_reputation, s.category, s.country, s.region,
                              s.article_count_30d
                       FROM articles a JOIN sources s ON s.id = a.source_id
                       WHERE a.status = 'pending'
                       ORDER BY a.fetched_at ASC LIMIT %s""",
                    (cfg.LLM_BATCH_SIZE,),
                )
                batch = cur.fetchall()
            if not batch:
                break

            # Story-obscurity needs counts of articles sharing each title_hash
            # in the last 24h. One grouped query per batch is enough; perfect
            # accuracy isn't required since maintenance.py refreshes nightly.
            title_hashes = [a["title_hash"] for a in batch if a.get("title_hash")]
            story_counts = {}
            if title_hashes:
                placeholders = ", ".join(["%s"] * len(title_hashes))
                with conn.cursor() as cur:
                    cur.execute(
                        f"""SELECT title_hash, COUNT(*) AS n FROM articles
                            WHERE title_hash IN ({placeholders})
                              AND fetched_at >= UTC_TIMESTAMP() - INTERVAL 1 DAY
                            GROUP BY title_hash""",
                        title_hashes,
                    )
                    story_counts = {r["title_hash"]: r["n"] for r in cur.fetchall()}

            # Step 1: rules features (always succeeds)
            rules_features = {}
            for art in batch:
                rules_features[art["id"]] = compute_rules_features(
                    {"title": art["title"], "summary": art["summary"]},
                    {
                        "source_lean": art["source_lean"],
                        "source_reputation": art["source_reputation"],
                        "category": art["category"],
                        "country": art["country"],
                        "region": art["region"],
                    },
                )

            # Step 2: LLM features (lean, objectivity). Fall back to source-level on failure.
            llm_by_id = {}
            usage = None
            try:
                items = [
                    (a["id"], a["source_name"], float(a["source_lean"]),
                     a["title"], a["summary"] or "")
                    for a in batch
                ]
                res = classify_batch_llm(cfg.ANTHROPIC_API_KEY, cfg.ANTHROPIC_MODEL, items)
                llm_by_id = res["by_id"]
                usage = res["usage"]
            except LLMUnavailable as e:
                logger.info("LLM unavailable, using source-level defaults: %s", e)

            # Step 2b: paywall detection per article. HTTP-bound, so we honour
            # the wallclock budget here and fall through to write whatever we have.
            paywall_by_id = {}
            for art in batch:
                if time.time() - start >= cfg.CLASSIFY_BUDGET_SECONDS:
                    break
                paywall_by_id[art["id"]] = detect_paywall(art.get("url"), session=http)

            # Step 2c: body extraction per article (for the in-app reader).
            # Skip when paywall said "locked" — extraction would just record
            # error rows and burn budget. Same wallclock gate.
            bodies_by_id = {}
            for art in batch:
                if time.time() - start >= cfg.CLASSIFY_BUDGET_SECONDS:
                    break
                if paywall_by_id.get(art["id"], 0.0) >= 1.0:
                    continue
                bodies_by_id[art["id"]] = extract_body(art.get("url"), session=http)

            # Step 3: write features + bylines
            with conn.cursor() as cur:
                for art in batch:
                    aid = art["id"]
                    rf = rules_features[aid]
                    llm = llm_by_id.get(aid, {
                        "political_lean": float(art["source_lean"]),  # fallback
                        "objectivity": 0.5,
                    })
                    src_obs = source_obscurity_score(art.get("article_count_30d") or 0)
                    th = art.get("title_hash")
                    story_obs = story_obscurity_score(story_counts.get(th, 1)) if th else 0.5
                    paywall = paywall_by_id.get(aid, 0.5)  # budget cut-off => suspected
                    cur.execute(
                        """INSERT INTO article_features
                           (article_id, political_lean, reading_level, objectivity, info_density,
                            journalist_reputation, source_lean, source_reputation, category,
                            country, region, popularity, story_obscurity, source_obscurity,
                            paywall, classifier_version)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                           ON DUPLICATE KEY UPDATE
                              political_lean=VALUES(political_lean),
                              reading_level=VALUES(reading_level),
                              objectivity=VALUES(objectivity),
                              info_density=VALUES(info_density),
                              journalist_reputation=VALUES(journalist_reputation),
                              source_lean=VALUES(source_lean),
                              source_reputation=VALUES(source_reputation),
                              category=VALUES(category),
                              country=VALUES(country),
                              region=VALUES(region),
                              story_obscurity=VALUES(story_obscurity),
                              source_obscurity=VALUES(source_obscurity),
                              paywall=VALUES(paywall),
                              classifier_version=VALUES(classifier_version),
                              classified_at=UTC_TIMESTAMP()""",
                        (
                            aid, llm["political_lean"], rf["reading_level"], llm["objectivity"],
                            rf["info_density"], rf["journalist_reputation"], rf["source_lean"],
                            rf["source_reputation"], rf["category"], rf["country"], rf["region"],
                            0.0, story_obs, src_obs, paywall, cfg.CLASSIFIER_VERSION,
                        ),
                    )
                    # bylines
                    for byname in split_bylines(art.get("byline") or ""):
                        jid = _ensure_journalist(cur, byname, byname.title())
                        cur.execute(
                            "INSERT IGNORE INTO article_journalists (article_id, journalist_id) VALUES (%s, %s)",
                            (aid, jid),
                        )
                    # body for the in-app reader (may be absent if budget ran out)
                    body = bodies_by_id.get(aid)
                    if body is not None:
                        cur.execute(
                            """INSERT INTO article_bodies
                               (article_id, body_text, body_html, lead_image, author,
                                word_count, extractor, status)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                               ON DUPLICATE KEY UPDATE
                                  body_text=VALUES(body_text),
                                  body_html=VALUES(body_html),
                                  lead_image=VALUES(lead_image),
                                  author=VALUES(author),
                                  word_count=VALUES(word_count),
                                  extractor=VALUES(extractor),
                                  status=VALUES(status),
                                  extracted_at=UTC_TIMESTAMP()""",
                            (
                                aid, body.get("body_text"), body.get("body_html"),
                                body.get("lead_image"), body.get("author"),
                                body.get("word_count", 0), "trafilatura",
                                body.get("status", "error"),
                            ),
                        )
                    _assign_story_id(cur, art)
                    cur.execute("UPDATE articles SET status='classified' WHERE id=%s", (aid,))

                if usage:
                    cur.execute(
                        """INSERT INTO llm_usage (model, input_tokens, output_tokens,
                           cache_read_tokens, articles, est_cost_usd)
                           VALUES (%s,%s,%s,%s,%s,%s)""",
                        (
                            usage.get("model"), usage.get("input_tokens", 0),
                            usage.get("output_tokens", 0), usage.get("cache_read_tokens", 0),
                            len(llm_by_id), usage.get("est_cost_usd", 0.0),
                        ),
                    )
                    llm_articles += len(llm_by_id)
                    cost_total += usage.get("est_cost_usd", 0.0)
            conn.commit()
            classified_total += len(batch)

            if classified_total >= cfg.CLASSIFY_BATCH_LIMIT:
                break

        msg = f"classified={classified_total} llm_articles={llm_articles} cost_usd={cost_total:.4f}"
        logger.info(msg)
        db_log(conn, JOB, "info", msg)
    finally:
        http.close()
        conn.close()


if __name__ == "__main__":
    main()
