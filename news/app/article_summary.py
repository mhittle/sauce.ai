"""Read-side helpers for the cached 3-bullet TL;DR (article_summaries).

The write side lives in jobs/classify_pending.py (via
app.classifier.summary). This module is the request-path reader used by the
feed's lazy TL;DR panel and the reader view. It degrades to an empty list if
the article_summaries table is absent (migration not yet applied) so neither
user route 500s before the migration lands.
"""
import json

import pymysql

from .classifier.summary import sanitize_bullets
from .db import query


def parse_bullets(raw_json):
    """Parse a stored bullets_json string into a clean bullet list. Tolerant
    of NULL / malformed JSON (returns [])."""
    if not raw_json:
        return []
    try:
        data = json.loads(raw_json)
    except (TypeError, ValueError):
        return []
    return sanitize_bullets(data)


def load_bullets(article_id):
    """Fetch the cached TL;DR bullets for one article. Returns [] when there
    is no summary, or when article_summaries doesn't exist yet on this host
    (the migration is applied post-deploy)."""
    try:
        row = query(
            "SELECT bullets_json FROM article_summaries WHERE article_id = %s",
            (article_id,),
            one=True,
        )
    except pymysql.err.ProgrammingError:
        # 1146 "table doesn't exist": migration not applied yet. Degrade.
        return []
    if not row:
        return []
    return parse_bullets(row.get("bullets_json"))
