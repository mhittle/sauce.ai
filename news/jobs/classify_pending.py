#!/usr/bin/env python3
"""Classify pending articles with rules + (optional) LLM.

Run every ~5 minutes from cron. Walltime-budgeted so a stuck LLM call can't
exhaust shared-host CPU quota.
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import requests
from requests.adapters import HTTPAdapter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _bootstrap import Config, get_conn, setup_logging, db_log, job_lock, AlreadyRunning
from app import classify_topup
from app.classifier import (
    compute_rules_features, classify_batch_llm, LLMUnavailable, normalize_byline,
    source_obscurity_score, story_obscurity_score, detect_paywall, popularity_score,
    summarize_batch_llm,
)
from app.classifier.llm import LLM_PERCEPTION_KEYS, LLM_PERCEPTION_DEFAULT
from app.classifier.rules import split_bylines
from app.extractor import extract_body
from app.geo import geocode_place

JOB = "classify_pending"
logger = setup_logging(JOB)

SIMHASH_HAMMING_MAX = 8
CLUSTER_LOOKBACK_HOURS = 48
HTTP_WORKERS = 10


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
    if not candidate and my_sim:
        cur.execute(
            """SELECT a2.id, a2.story_id, BIT_COUNT(a2.simhash ^ %s) AS hd
               FROM articles a2
               WHERE a2.fetched_at >= UTC_TIMESTAMP() - INTERVAL %s HOUR
                 AND a2.simhash IS NOT NULL
                 AND a2.simhash <> 0
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


NOLLM_SUFFIX = "-nollm"


def _classifier_version(aid, llm_by_id, base):
    """Tag rows that fell back to source-level lean/objectivity (LLM
    unavailable) with a distinct version so they're queryable and the
    per-tick reclassify pass can find them (BUG-019)."""
    return base if aid in llm_by_id else base + NOLLM_SUFFIX


def _ensure_journalist(cur, normalized, display, first_seen=None):
    """Look up (or create) a journalist row. `first_seen` is the article's
    published_at: seeding tenure from publish date instead of row-insert time
    keeps `journalist_reputation` from being a function of when our DB first
    happened to see the byline (BUG-017). For an existing journalist, pull
    first_seen_at earlier if this article predates it."""
    cur.execute("SELECT id FROM journalists WHERE normalized_name=%s", (normalized,))
    row = cur.fetchone()
    if row:
        if first_seen is not None:
            cur.execute(
                "UPDATE journalists SET first_seen_at=%s "
                "WHERE id=%s AND first_seen_at > %s",
                (first_seen, row["id"], first_seen),
            )
        return row["id"]
    if first_seen is not None:
        cur.execute(
            "INSERT INTO journalists (normalized_name, display_name, first_seen_at) "
            "VALUES (%s, %s, %s)",
            (normalized, display[:200], first_seen),
        )
    else:
        cur.execute(
            "INSERT INTO journalists (normalized_name, display_name) VALUES (%s, %s)",
            (normalized, display[:200]),
        )
    return cur.lastrowid


def _reclassify_nollm(conn, cfg, deadline):
    """Re-run the LLM over rows previously classified with the `-nollm`
    fallback (BUG-019). Bounded: one LLM batch per tick, only when the
    pending queue is already drained and wallclock budget remains. Returns
    (reclassified_count, cost_usd). No-ops (and clears nothing) if the LLM is
    still unavailable, so a persistent outage just leaves the rows tagged for
    the next tick."""
    if time.time() >= deadline:
        return 0, 0.0
    marker = cfg.CLASSIFIER_VERSION + NOLLM_SUFFIX
    conn.ping(reconnect=True)
    with conn.cursor() as cur:
        cur.execute(
            """SELECT a.id, a.title, a.summary, s.name AS source_name, s.source_lean
               FROM article_features f
               JOIN articles a ON a.id = f.article_id
               JOIN sources s ON s.id = a.source_id
               WHERE f.classifier_version = %s
               ORDER BY f.classified_at ASC
               LIMIT %s""",
            (marker, cfg.LLM_BATCH_SIZE),
        )
        rows = cur.fetchall()
    if not rows:
        return 0, 0.0

    items = [
        (r["id"], r["source_name"], float(r["source_lean"] or 0.0),
         r["title"], r["summary"] or "")
        for r in rows
    ]
    try:
        res = classify_batch_llm(cfg.ANTHROPIC_API_KEY, cfg.ANTHROPIC_MODEL, items)
    except LLMUnavailable as e:
        logger.info("reclassify: LLM still unavailable, leaving %d rows tagged: %s",
                    len(rows), e)
        return 0, 0.0

    by_id = res["by_id"]
    usage = res.get("usage") or {}
    conn.ping(reconnect=True)
    with conn.cursor() as cur:
        for aid, vals in by_id.items():
            place = (vals.get("primary_location") or "").strip() or None
            lat = lng = None
            if place:
                resolved = geocode_place(place)
                if resolved:
                    lat, lng, _label = resolved
            cur.execute(
                """UPDATE article_features
                   SET political_lean=%s, objectivity=%s,
                       tone_calmness=%s, sensationalism=%s, analysis_depth=%s,
                       emotional_charge=%s, hedging=%s, solution_orientation=%s,
                       geo_lat=%s, geo_lng=%s, geo_place=%s,
                       classifier_version=%s, classified_at=UTC_TIMESTAMP()
                   WHERE article_id=%s""",
                (vals["political_lean"], vals["objectivity"],
                 vals["tone_calmness"], vals["sensationalism"], vals["analysis_depth"],
                 vals["emotional_charge"], vals["hedging"], vals["solution_orientation"],
                 lat, lng, place,
                 cfg.CLASSIFIER_VERSION, aid),
            )
        if usage:
            cur.execute(
                """INSERT INTO llm_usage (model, input_tokens, output_tokens,
                   cache_read_tokens, articles, est_cost_usd)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (usage.get("model"), usage.get("input_tokens", 0),
                 usage.get("output_tokens", 0), usage.get("cache_read_tokens", 0),
                 len(by_id), usage.get("est_cost_usd", 0.0)),
            )
    conn.commit()
    return len(by_id), usage.get("est_cost_usd", 0.0)


def _table_exists(conn, name):
    """One-time capability probe. The TL;DR pass writes article_summaries
    every tick once deployed; if the migration hasn't been applied yet we
    skip the pass entirely rather than crash the classify write (the BUG-025
    lesson — a cron-written column/table that's missing must degrade, not
    freeze the feed)."""
    conn.ping(reconnect=True)
    with conn.cursor() as cur:
        cur.execute("SHOW TABLES LIKE %s", (name,))
        return cur.fetchone() is not None


def _resolve_signal_path():
    """Match the path the feed touches: ``<news>/logs/classify_topup.signal``
    unless ``CLASSIFY_TOPUP_SIGNAL_PATH`` overrides it."""
    override = getattr(Config, "CLASSIFY_TOPUP_SIGNAL_PATH", "") or None
    app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return classify_topup.signal_path_for(app_root, override)


def main():
    triggered_only = "--triggered-only" in sys.argv[1:]
    if triggered_only:
        signal_path = _resolve_signal_path()
        max_age = int(getattr(Config, "CLASSIFY_TOPUP_SIGNAL_MAX_AGE",
                              classify_topup.DEFAULT_SIGNAL_MAX_AGE_SECONDS))
        if not classify_topup.signal_is_fresh(signal_path, time.time(), max_age):
            logger.info("%s --triggered-only: no fresh signal, exiting", JOB)
            return
    try:
        with job_lock(JOB):
            if triggered_only:
                # Consume INSIDE the lock so a concurrent feed touch that
                # races us just re-creates the signal for the next 1-min
                # tick to act on.
                classify_topup.consume_signal(_resolve_signal_path())
            _run()
    except AlreadyRunning:
        logger.info("%s lock held by another process; skipping this tick", JOB)


def _run():
    cfg = Config
    start = time.time()
    conn = get_conn()
    classified_total = llm_articles = summary_articles = 0
    cost_total = 0.0
    summary_model = cfg.SUMMARY_MODEL or cfg.ANTHROPIC_MODEL
    summaries_enabled = cfg.SUMMARY_ENABLED and _table_exists(conn, "article_summaries")
    if cfg.SUMMARY_ENABLED and not summaries_enabled:
        logger.info("TL;DR summaries: article_summaries table missing; skipping summary pass")
    http = requests.Session()
    # Default urllib3 pool is 10 hosts × 10 conns; we run HTTP_WORKERS=10
    # concurrently across up to that many distinct hosts per batch, so bump
    # the cache to avoid pool-full warnings and serial waits.
    _adapter = HTTPAdapter(pool_connections=HTTP_WORKERS * 2, pool_maxsize=HTTP_WORKERS * 2)
    http.mount("http://", _adapter)
    http.mount("https://", _adapter)
    try:
        while time.time() - start < cfg.CLASSIFY_BUDGET_SECONDS:
            # Shared-host MySQL aggressively closes idle sockets; this loop
            # spends 30-200s in LLM + paywall + body-extraction HTTP between
            # batches, so the socket is often half-dead by the time we get
            # here. ping(reconnect=True) is a no-op when alive.
            conn.ping(reconnect=True)
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

            # Popularity seed: an article can trend on Reddit/HN while it's
            # still 'pending', so popularity_signals may already have rows for
            # it. Seed from those instead of writing 0.0 (BUG-016). The
            # nightly maintenance reconciliation is the authoritative
            # catch-up; this just avoids a multi-hour 0.0 window.
            pop_seed = {}
            ids = [a["id"] for a in batch]
            if ids:
                ph = ", ".join(["%s"] * len(ids))
                with conn.cursor() as cur:
                    cur.execute(
                        f"""SELECT article_id, MAX(score + 2 * comments) AS eng
                            FROM popularity_signals
                            WHERE article_id IN ({ph})
                            GROUP BY article_id""",
                        ids,
                    )
                    for r in cur.fetchall():
                        # eng is already score+2*comments; pass as score with
                        # comments=0 so the shared curve is applied verbatim.
                        pop_seed[r["article_id"]] = popularity_score(r["eng"], 0)

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

            # Step 2b: paywall detection — fanned out across HTTP_WORKERS threads.
            # Articles are independent (different hosts, no shared state in
            # detect_paywall beyond the thread-safe session connection pool).
            paywall_by_id = {}
            if time.time() - start < cfg.CLASSIFY_BUDGET_SECONDS:
                with ThreadPoolExecutor(max_workers=HTTP_WORKERS) as ex:
                    fut_to_id = {
                        ex.submit(detect_paywall, art.get("url"), session=http): art["id"]
                        for art in batch
                    }
                    for fut in as_completed(fut_to_id):
                        aid = fut_to_id[fut]
                        try:
                            paywall_by_id[aid] = fut.result()
                        except Exception as e:
                            logger.warning("paywall probe failed for %d: %s", aid, e)
                            paywall_by_id[aid] = 0.5  # SUSPECTED

            # Step 2c: body extraction — same fan-out, skipping articles whose
            # paywall came back "locked" (extraction would just record an
            # error row and burn HTTP budget).
            bodies_by_id = {}
            if time.time() - start < cfg.CLASSIFY_BUDGET_SECONDS:
                to_extract = [
                    art for art in batch
                    if paywall_by_id.get(art["id"], 0.0) < 1.0
                ]
                with ThreadPoolExecutor(max_workers=HTTP_WORKERS) as ex:
                    fut_to_id = {
                        ex.submit(extract_body, art.get("url"), session=http): art["id"]
                        for art in to_extract
                    }
                    for fut in as_completed(fut_to_id):
                        aid = fut_to_id[fut]
                        try:
                            bodies_by_id[aid] = fut.result()
                        except Exception as e:
                            logger.warning("body extraction failed for %d: %s", aid, e)

            # Step 2d: 3-bullet TL;DR — a separate, isolated LLM pass over the
            # gated subset (reputation above floor, not paywalled, real body
            # extracted). Decoupled from the judgments call: any failure is
            # swallowed so a summary problem can never stall classification or
            # degrade ranking. Summarizes the extracted body, not the RSS blurb.
            summaries_by_id = {}
            sum_usage = None
            if summaries_enabled and time.time() - start < cfg.CLASSIFY_BUDGET_SECONDS:
                sum_items = []
                for art in batch:
                    aid = art["id"]
                    if float(art.get("source_reputation") or 0.0) <= cfg.SUMMARY_MIN_REPUTATION:
                        continue
                    if paywall_by_id.get(aid, 0.5) >= cfg.SUMMARY_MAX_PAYWALL:
                        continue
                    body = bodies_by_id.get(aid)
                    if not body or body.get("status") != "ok" or not body.get("body_text"):
                        continue
                    sum_items.append((aid, art["title"], body["body_text"]))
                if sum_items:
                    try:
                        sres = summarize_batch_llm(
                            cfg.ANTHROPIC_API_KEY, summary_model, sum_items,
                            max_body_chars=cfg.SUMMARY_MAX_BODY_CHARS)
                        summaries_by_id = sres["by_id"]
                        sum_usage = sres.get("usage") or None
                    except LLMUnavailable as e:
                        logger.info("TL;DR summary pass unavailable: %s", e)
                    except Exception as e:
                        logger.warning("TL;DR summary pass failed: %s", e)

            # Step 3: write features + bylines. Ping again — paywall + body
            # extraction above can spend another 30-100s idle on the socket.
            conn.ping(reconnect=True)
            with conn.cursor() as cur:
                for art in batch:
                    aid = art["id"]
                    rf = rules_features[aid]
                    llm = llm_by_id.get(aid)
                    if llm is None:
                        llm = {
                            "political_lean": float(art["source_lean"]),  # fallback
                            "objectivity": 0.5,
                            "primary_location": "",
                        }
                        for k in LLM_PERCEPTION_KEYS:
                            llm[k] = LLM_PERCEPTION_DEFAULT
                    geo_lat = geo_lng = None
                    geo_place = (llm.get("primary_location") or "").strip() or None
                    if geo_place:
                        resolved = geocode_place(geo_place)
                        if resolved:
                            geo_lat, geo_lng, _label = resolved
                    src_obs = source_obscurity_score(art.get("article_count_30d") or 0)
                    th = art.get("title_hash")
                    story_obs = story_obscurity_score(story_counts.get(th, 1)) if th else 0.5
                    paywall = paywall_by_id.get(aid, 0.5)  # budget cut-off => suspected
                    cur.execute(
                        """INSERT INTO article_features
                           (article_id, political_lean, reading_level, objectivity, info_density,
                            journalist_reputation, source_lean, source_reputation, category,
                            country, region, geo_lat, geo_lng, geo_place,
                            popularity, story_obscurity, source_obscurity,
                            paywall,
                            tone_calmness, sensationalism, analysis_depth, emotional_charge,
                            hedging, solution_orientation,
                            headline_length, caps_ratio, punctuation_intensity,
                            numeric_density, question_headline, quote_present,
                            classifier_version)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                                   %s,%s,%s,
                                   %s,%s,%s,%s,
                                   %s,%s,%s,%s,%s,%s,
                                   %s,%s,%s,%s,%s,%s,
                                   %s)
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
                              geo_lat=VALUES(geo_lat),
                              geo_lng=VALUES(geo_lng),
                              geo_place=VALUES(geo_place),
                              story_obscurity=VALUES(story_obscurity),
                              source_obscurity=VALUES(source_obscurity),
                              paywall=VALUES(paywall),
                              tone_calmness=VALUES(tone_calmness),
                              sensationalism=VALUES(sensationalism),
                              analysis_depth=VALUES(analysis_depth),
                              emotional_charge=VALUES(emotional_charge),
                              hedging=VALUES(hedging),
                              solution_orientation=VALUES(solution_orientation),
                              headline_length=VALUES(headline_length),
                              caps_ratio=VALUES(caps_ratio),
                              punctuation_intensity=VALUES(punctuation_intensity),
                              numeric_density=VALUES(numeric_density),
                              question_headline=VALUES(question_headline),
                              quote_present=VALUES(quote_present),
                              classifier_version=VALUES(classifier_version),
                              classified_at=UTC_TIMESTAMP()""",
                        (
                            aid, llm["political_lean"], rf["reading_level"], llm["objectivity"],
                            rf["info_density"], rf["journalist_reputation"], rf["source_lean"],
                            rf["source_reputation"], rf["category"], rf["country"], rf["region"],
                            geo_lat, geo_lng, geo_place,
                            pop_seed.get(aid, 0.0), story_obs, src_obs, paywall,
                            llm["tone_calmness"], llm["sensationalism"], llm["analysis_depth"],
                            llm["emotional_charge"], llm["hedging"], llm["solution_orientation"],
                            rf["headline_length"], rf["caps_ratio"], rf["punctuation_intensity"],
                            rf["numeric_density"], rf["question_headline"], rf["quote_present"],
                            _classifier_version(aid, llm_by_id, cfg.CLASSIFIER_VERSION),
                        ),
                    )
                    # bylines
                    for byname in split_bylines(art.get("byline") or ""):
                        jid = _ensure_journalist(cur, byname, byname.title(),
                                                 art.get("published_at"))
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
                    # 3-bullet TL;DR (gated subset only; absent otherwise).
                    bullets = summaries_by_id.get(aid)
                    if bullets:
                        cur.execute(
                            """INSERT INTO article_summaries (article_id, bullets_json, model)
                               VALUES (%s,%s,%s)
                               ON DUPLICATE KEY UPDATE
                                  bullets_json=VALUES(bullets_json),
                                  model=VALUES(model),
                                  generated_at=UTC_TIMESTAMP()""",
                            (aid, json.dumps(bullets), summary_model),
                        )
                    _assign_story_id(cur, art)
                    cur.execute("UPDATE articles SET status='classified' WHERE id=%s", (aid,))

                if sum_usage:
                    cur.execute(
                        """INSERT INTO llm_usage (model, input_tokens, output_tokens,
                           cache_read_tokens, articles, est_cost_usd)
                           VALUES (%s,%s,%s,%s,%s,%s)""",
                        (
                            sum_usage.get("model"), sum_usage.get("input_tokens", 0),
                            sum_usage.get("output_tokens", 0), sum_usage.get("cache_read_tokens", 0),
                            len(summaries_by_id), sum_usage.get("est_cost_usd", 0.0),
                        ),
                    )
                    summary_articles += len(summaries_by_id)
                    cost_total += sum_usage.get("est_cost_usd", 0.0)

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

        # Pending queue drained (or limit hit). If budget remains, spend one
        # LLM batch healing rows previously stuck on the -nollm fallback.
        reclassified = 0
        try:
            reclassified, recost = _reclassify_nollm(
                conn, cfg, start + cfg.CLASSIFY_BUDGET_SECONDS)
            cost_total += recost
        except Exception as e:
            logger.warning("reclassify pass failed: %s", e)

        msg = (f"classified={classified_total} llm_articles={llm_articles} "
               f"summaries={summary_articles} "
               f"reclassified={reclassified} cost_usd={cost_total:.4f}")
        logger.info(msg)
        db_log(conn, JOB, "info", msg)
    finally:
        http.close()
        conn.close()


if __name__ == "__main__":
    main()
