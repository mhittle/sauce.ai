"""Across-the-spectrum in-feed: pick a small sibling sample for a card.

The "+N angles" pill on a multi-source feed card expands inline (HTMX) to
show a handful of *other* outlets' coverage of the same deduplicated story
without leaving the feed — the ambient, everyday cousin of the full story
dossier at /story/<id>. This module is the pure, Flask-free selection core
(mirrors the helper convention of `discussion.py` / `trending.py`): given a
story cluster's members it returns a lean-diverse, source-deduped sample.

`lean_bucket`'s thresholds intentionally mirror
`app.routes.story.LEAN_LEFT_THRESHOLD` / `LEAN_RIGHT_THRESHOLD` so the
in-feed peek and the full dossier bucket an article identically. Keep the
two in sync if either moves.
"""
import datetime

LEAN_LEFT_THRESHOLD = -0.2
LEAN_RIGHT_THRESHOLD = 0.2

BUCKET_ORDER = ("left", "center", "right")


def lean_bucket(lean):
    if lean is None:
        return "center"
    if lean <= LEAN_LEFT_THRESHOLD:
        return "left"
    if lean >= LEAN_RIGHT_THRESHOLD:
        return "right"
    return "center"


def _recency_key(member):
    return (member.get("published_at") or datetime.datetime.min, member["id"])


def pick_spectrum_sample(members, exclude_id, limit=3):
    """Choose up to `limit` cluster members to preview under a feed card.

    - `exclude_id` (the card's own canonical article) is dropped so the
      peek only shows *other* angles.
    - At most one article per source — three headlines from the same wire
      reprint is not "across the spectrum".
    - Round-robin across left/center/right so the sample spans the
      spectrum even when one side dominates the cluster, newest first
      within each side. Deterministic given the same input.
    """
    by_bucket = {b: [] for b in BUCKET_ORDER}
    for m in members:
        if m["id"] == exclude_id:
            continue
        by_bucket[lean_bucket(m.get("political_lean"))].append(m)
    for b in BUCKET_ORDER:
        by_bucket[b].sort(key=_recency_key, reverse=True)

    chosen = []
    seen_sources = set()
    progressed = True
    while len(chosen) < limit and progressed:
        progressed = False
        for b in BUCKET_ORDER:
            if len(chosen) >= limit:
                break
            bucket = by_bucket[b]
            while bucket:
                m = bucket.pop(0)
                sid = m.get("source_id")
                if sid in seen_sources:
                    continue
                chosen.append(m)
                seen_sources.add(sid)
                progressed = True
                break
    return chosen
