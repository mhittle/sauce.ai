#!/usr/bin/env python3
"""Nightly: prune old articles/sessions, recompute journalist reputation."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _bootstrap import Config, get_conn, setup_logging, db_log

JOB = "maintenance"
logger = setup_logging(JOB)


def main():
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

            # Recompute journalist reputation:
            #   rep = 0.5 * avg(source_reputation across articles) + 0.5 * tenure_score
            #   tenure_score = min(1, days_since_first_seen / 365)
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
                       j.computed_reputation = 0.5 * COALESCE(agg.avg_rep, 0.5)
                          + 0.5 * LEAST(1.0, DATEDIFF(UTC_TIMESTAMP(), j.first_seen_at) / 365.0)
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

            # Trim old pipeline logs
            cur.execute("DELETE FROM pipeline_log WHERE ts < UTC_TIMESTAMP() - INTERVAL 14 DAY")

        conn.commit()
        msg = f"pruned_articles={pruned} pruned_sessions={sess_pruned}"
        logger.info(msg)
        db_log(conn, JOB, "info", msg)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
