#!/usr/bin/env python3
"""Nightly: prune old articles/sessions, recompute journalist reputation."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _bootstrap import Config, get_conn, setup_logging, db_log, job_lock, AlreadyRunning
from app.classifier.rules import _POPULARITY_LN_DENOM

JOB = "maintenance"
logger = setup_logging(JOB)


def main():
    try:
        with job_lock(JOB):
            _run()
    except AlreadyRunning:
        logger.info("%s lock held by another process; skipping this tick", JOB)


def _run():
    cfg = Config
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # Prune old articles (cascades to features, popularity, article_journalists)
            cur.execute(
                "DELETE FROM articles WHERE fetched_at < UTC_TIMESTAMP() - INTERVAL %s DAY",
                (cfg.ARTICLE_RETENTION_DAYS,),
            )
            pruned = cur.rowcount

            # Prune expired sessions
            cur.execute("DELETE FROM sessions WHERE expires_at < UTC_TIMESTAMP()")
            sess_pruned = cur.rowcount

            # Refresh sources.article_count_30d (drives source_obscurity)
            cur.execute(
                """UPDATE sources s
                   LEFT JOIN (
                     SELECT source_id, COUNT(*) AS n
                     FROM articles
                     WHERE fetched_at >= UTC_TIMESTAMP() - INTERVAL 30 DAY
                     GROUP BY source_id
                   ) c ON c.source_id = s.id
                   SET s.article_count_30d = COALESCE(c.n, 0)"""
            )

            # Recompute source_obscurity on recent article_features rows.
            # Log-scaled: log10(count+1)/log10(1001) → obscurity = 1 - that.
            cur.execute(
                """UPDATE article_features f
                   JOIN articles a ON a.id = f.article_id
                   JOIN sources s  ON s.id = a.source_id
                   SET f.source_obscurity = GREATEST(0, LEAST(1,
                         1 - (LOG10(s.article_count_30d + 1) / 3)
                       ))
                   WHERE a.fetched_at >= UTC_TIMESTAMP() - INTERVAL 7 DAY"""
            )

            # Recompute story_obscurity on recent article_features rows using
            # the actual 24h cluster size. Log20 normalization matches
            # story_obscurity_score() in rules.py.
            cur.execute(
                """UPDATE article_features f
                   JOIN articles a ON a.id = f.article_id
                   JOIN (
                     SELECT title_hash, COUNT(*) AS n
                     FROM articles
                     WHERE title_hash IS NOT NULL
                       AND fetched_at >= UTC_TIMESTAMP() - INTERVAL 1 DAY
                     GROUP BY title_hash
                   ) c ON c.title_hash = a.title_hash
                   SET f.story_obscurity = GREATEST(0, LEAST(1,
                         1 - (LOG10(GREATEST(c.n,1)) / LOG10(20))
                       ))
                   WHERE a.fetched_at >= UTC_TIMESTAMP() - INTERVAL 7 DAY"""
            )

            # Reconcile popularity from popularity_signals. classify_pending
            # writes popularity=0.0 on first insert and popularity_poll only
            # UPDATEs rows that already exist, so anything that trended while
            # still 'pending' permanently lost its signal (BUG-016). This is
            # the authoritative catch-up: recompute from the raw signals using
            # the same log curve as app.classifier.popularity_score
            #   pop = LN(1 + score + 2*comments) / LN(1 + engagement_cap)
            cur.execute(
                """UPDATE article_features f
                   JOIN articles a ON a.id = f.article_id
                   JOIN (
                     SELECT article_id, MAX(score + 2 * comments) AS engagement
                     FROM popularity_signals
                     GROUP BY article_id
                   ) ps ON ps.article_id = f.article_id
                   SET f.popularity = GREATEST(0, LEAST(1,
                         LN(1 + ps.engagement) / %s
                       ))
                   WHERE a.fetched_at >= UTC_TIMESTAMP() - INTERVAL 7 DAY""",
                (_POPULARITY_LN_DENOM,),
            )

            # Recompute journalist reputation. Floored at the journalist's
            # average source reputation so a parseable byline can never score
            # below the no-byline fallback (which is the article's own
            # source_reputation); tenure is upside-only (BUG-017).
            #   base   = avg(source_reputation across their articles)
            #   tenure = min(1, max(0, days_since_first_seen) / 365)
            #   rep    = max(base, 0.5*base + 0.5*tenure)
            cur.execute(
                """UPDATE journalists j
                   LEFT JOIN (
                     SELECT aj.journalist_id,
                            AVG(s.source_reputation) AS avg_rep,
                            COUNT(*) AS n
                     FROM article_journalists aj
                     JOIN articles a ON a.id = aj.article_id
                     JOIN sources s ON s.id = a.source_id
                     GROUP BY aj.journalist_id
                   ) agg ON agg.journalist_id = j.id
                   SET j.article_count = COALESCE(agg.n, 0),
                       j.computed_reputation = GREATEST(
                         COALESCE(agg.avg_rep, 0.5),
                         0.5 * COALESCE(agg.avg_rep, 0.5)
                           + 0.5 * LEAST(1.0,
                               GREATEST(0, DATEDIFF(UTC_TIMESTAMP(), j.first_seen_at)) / 365.0)
                       )
                """
            )

            # Propagate journalist reputation onto recent article_features
            cur.execute(
                """UPDATE article_features f
                   JOIN articles a ON a.id = f.article_id
                   JOIN article_journalists aj ON aj.article_id = a.id
                   JOIN journalists j ON j.id = aj.journalist_id
                   SET f.journalist_reputation = j.computed_reputation
                   WHERE a.fetched_at >= UTC_TIMESTAMP() - INTERVAL 7 DAY"""
            )

            # Prune old article bodies. Independent of article retention so
            # the bodies window can be tightened (storage cost) without
            # affecting feed history. Bookmarks override this once /saved
            # ships (see roadmap).
            cur.execute(
                "DELETE FROM article_bodies WHERE extracted_at < UTC_TIMESTAMP() - INTERVAL %s DAY",
                (cfg.BODY_RETENTION_DAYS,),
            )
            bodies_pruned = cur.rowcount

            # Heal any orphaned story_ids: rows where story_id IS NULL or
            # points at a pruned article. Self-assign so they become their
            # own (singleton) cluster again.
            cur.execute(
                """UPDATE articles a
                   LEFT JOIN articles c ON c.id = a.story_id
                   SET a.story_id = a.id
                   WHERE a.story_id IS NULL OR c.id IS NULL"""
            )

            # Trim old pipeline logs
            cur.execute("DELETE FROM pipeline_log WHERE ts < UTC_TIMESTAMP() - INTERVAL 14 DAY")

        conn.commit()
        msg = f"pruned_articles={pruned} pruned_sessions={sess_pruned} pruned_bodies={bodies_pruned}"
        logger.info(msg)
        db_log(conn, JOB, "info", msg)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
