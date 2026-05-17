"""Techmeme-style discussion links.

`popularity_poll` already matches Reddit/HN threads to our articles every
30 min for the popularity score; it now also stores the thread `permalink`
and (for Reddit) the `subreddit`. These helpers read that back so the feed
card and story dossier can show a "Discussion: Hacker News (142) ·
r/technology (89)" line linking out to the conversation.

`discussion_label` and `_merge` are pure and unit-tested directly; the two
query-backed functions are exercised by monkeypatching `query`.
"""
from .db import query


def discussion_label(source, subreddit):
    if source == "hn":
        return "Hacker News"
    if source == "reddit":
        return f"r/{subreddit}" if subreddit else "Reddit"
    return source


def _rows_for(article_ids):
    placeholders = ",".join(["%s"] * len(article_ids))
    return query(
        f"""SELECT article_id, source, comments, permalink, subreddit
            FROM popularity_signals
            WHERE permalink IS NOT NULL
              AND article_id IN ({placeholders})""",
        tuple(article_ids),
    )


def _entry(row):
    return {
        "label": discussion_label(row["source"], row.get("subreddit")),
        "comments": row["comments"] or 0,
        "url": row["permalink"],
    }


def discussions_for_articles(article_ids):
    """Map article_id -> list of {label, comments, url}, comments desc.

    Only articles with at least one matched discussion thread appear in the
    returned dict; callers should default missing ids to an empty list.
    """
    if not article_ids:
        return {}
    out = {}
    for r in _rows_for(article_ids):
        out.setdefault(r["article_id"], []).append(_entry(r))
    for entries in out.values():
        entries.sort(key=lambda e: e["comments"], reverse=True)
    return out


def _merge(rows):
    """Collapse rows across a story's cluster members into one list.

    Same thread URL can be matched against several cluster members (a
    syndicated reprint shares the Reddit/HN submission); dedupe by URL,
    keeping the highest comment count seen. Sorted comments desc.
    """
    by_url = {}
    for r in rows:
        e = _entry(r)
        prev = by_url.get(e["url"])
        if prev is None or e["comments"] > prev["comments"]:
            by_url[e["url"]] = e
    return sorted(by_url.values(), key=lambda e: e["comments"], reverse=True)


def discussions_for_story(article_ids):
    """Single merged discussion list for every member of a story cluster."""
    if not article_ids:
        return []
    return _merge(_rows_for(article_ids))
