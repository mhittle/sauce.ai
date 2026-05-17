"""Trending topics view at /trending.

`trending_poll` snapshots the Google Trends/News topic index plus the
articles matching each topic every ~30 min (`trending_topics` /
`trending_topic_articles`). This page reads that back and ranks topics
by **distinct outlet count** — "a topic 20 outlets cover beats one one
outlet covered 20 times" — so wire-syndicated noise doesn't dominate.
Each topic links to the story dossier(s) under it.

Visibility mirrors the feed/dossier: anonymous users see only global
(`sources.owner_id IS NULL`) articles; signed-in users also see their
own personal-feed articles, so a personal source can't inflate a
topic's public outlet count.
"""
from flask import Blueprint, render_template, g, current_app

from ..db import query
from ..trending import group_topic_stories

bp = Blueprint("trending", __name__)


@bp.route("/trending")
def index():
    cfg = current_app.config
    window = cfg["TRENDING_WINDOW_DAYS"]
    min_sources = cfg["TRENDING_MIN_SOURCES"]
    limit = cfg["TRENDING_PAGE_LIMIT"]
    per_topic = cfg["TRENDING_STORIES_PER_TOPIC"]

    u = getattr(g, "user", None)
    uid = u["id"] if u else None

    vis = "(s.owner_id IS NULL OR s.owner_id = %s)" if uid else "s.owner_id IS NULL"

    topic_params = [window]
    if uid:
        topic_params.append(uid)
    topic_params += [min_sources, limit]

    topics = query(
        f"""
        SELECT t.topic_key, t.label, t.origin, t.heat,
               COUNT(DISTINCT a.source_id)                 AS source_count,
               COUNT(DISTINCT COALESCE(a.story_id, a.id))  AS story_count,
               COUNT(*)                                    AS article_count,
               MAX(ta.match_score)                         AS top_match
        FROM trending_topics t
        JOIN trending_topic_articles ta ON ta.topic_key = t.topic_key
        JOIN articles a ON a.id = ta.article_id
        JOIN sources s ON s.id = a.source_id
        WHERE a.status = 'classified'
          AND a.published_at >= UTC_TIMESTAMP() - INTERVAL %s DAY
          AND {vis}
        GROUP BY t.topic_key, t.label, t.origin, t.heat
        HAVING source_count >= %s
        ORDER BY source_count DESC, t.heat DESC, top_match DESC
        LIMIT %s
        """,
        tuple(topic_params),
    )

    stories_by_topic = {}
    if topics:
        keys = [t["topic_key"] for t in topics]
        placeholders = ",".join(["%s"] * len(keys))
        story_params = list(keys) + [window]
        if uid:
            story_params.append(uid)
        story_rows = query(
            f"""
            SELECT ta.topic_key,
                   COALESCE(a.story_id, a.id)   AS story_id,
                   c.title                      AS story_title,
                   c.url                        AS story_url,
                   COUNT(DISTINCT a.source_id)  AS story_sources,
                   COUNT(*)                     AS story_articles,
                   MAX(ta.match_score)          AS story_match
            FROM trending_topic_articles ta
            JOIN articles a ON a.id = ta.article_id
            JOIN sources s ON s.id = a.source_id
            LEFT JOIN articles c ON c.id = COALESCE(a.story_id, a.id)
            WHERE ta.topic_key IN ({placeholders})
              AND a.status = 'classified'
              AND a.published_at >= UTC_TIMESTAMP() - INTERVAL %s DAY
              AND {vis}
            GROUP BY ta.topic_key, story_id, c.title, c.url
            ORDER BY ta.topic_key, story_sources DESC, story_match DESC
            """,
            tuple(story_params),
        )
        stories_by_topic = group_topic_stories(story_rows, per_topic=per_topic)

    return render_template(
        "trending.html",
        topics=topics,
        stories_by_topic=stories_by_topic,
        window_days=window,
        min_sources=min_sources,
    )
