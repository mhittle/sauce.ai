"""Blindspot — pure helpers for picking + labeling stories the reader's
algorithm is suppressing.

Flask-free / DB-free / LLM-free (mirrors `app.spectrum` /
`app.feed_diversify` / `app.breaking`). The route at
`app/routes/blindspot.py` runs the SQL (the global outlet-burst query +
the live feed-selection SELECT), prepares the per-story flag sets
(mute_hits, filter_hits, low_relevance), then calls these helpers to
order/label the result. Keeping the decision boundaries here lets the
test suite pin them without Haiku/DB/browser.

Hidden-reason priority is *mute* > *filter* > *low_relevance*. A story
that is muted is also (by definition) absent from the selection set, but
the user-facing label needs to name the responsible knob — "muted by your
keyword" is more actionable than "below your relevance bar."
"""
from __future__ import annotations

from typing import Iterable, Mapping, Optional


REASON_MUTED = "muted"
REASON_FILTERED = "filtered"
REASON_LOW_RELEVANCE = "low_relevance"

_REASON_LABELS = {
    REASON_MUTED: "Muted by your keyword",
    REASON_FILTERED: "Outside your hard filters",
    REASON_LOW_RELEVANCE: "Below your relevance bar",
}


def reason_label(reason: str, *, term: Optional[str] = None) -> str:
    """Plain-language one-liner for the responsible knob.

    `term` is the matched mute keyword (optional, used only when
    `reason == "muted"`). Unknown reasons fall back to the
    `low_relevance` label so the UI never renders a raw enum.
    """
    if reason == REASON_MUTED and term:
        return f"Muted by your keyword “{term}”"
    return _REASON_LABELS.get(reason, _REASON_LABELS[REASON_LOW_RELEVANCE])


def classify_blindspots(
    big_stories: Iterable[Mapping],
    shown_story_ids: Iterable,
    mute_hits: Optional[Mapping] = None,
    filter_hits: Optional[Iterable] = None,
    *,
    max_items: int = 8,
) -> list[dict]:
    """Pick the blindspots from a list of big-story candidates.

    Inputs:
      - ``big_stories``: rows from the outlet-burst query, each with at
        least ``story_id`` and ``outlet_count``. Input order is *not*
        trusted — we re-sort by outlet_count.
      - ``shown_story_ids``: the set of story_ids the live home feed
        would surface for this viewer (from
        ``feed._selected_story_ids``). A big story whose id is in here
        is *not* hidden — the feed is already showing it.
      - ``mute_hits``: optional ``{story_id: matched_term}`` map of
        big stories whose title+summary matches a mute keyword. Used
        only to label; the SQL mute clause already excludes these from
        ``shown_story_ids``, so they are already candidates.
      - ``filter_hits``: optional iterable of story_ids excluded by a
        hard filter (category / country / geo / threshold / source
        deny). Same deal — used only for labeling.

    Returns an ordered list (highest outlet_count first) of dicts:
      ``{story_id, outlet_count, hidden_reason, mute_term}``
    capped at ``max_items``. Empty inputs return ``[]``.

    Hidden-reason priority: mute > filter > low_relevance. The
    low-relevance bucket is the "passes all the filters and matches no
    mute, but the affinity score ranks it below the selection-pool
    cutoff" case — the most honest one to surface ("your algorithm
    didn't think you'd care about this").
    """
    try:
        cap = int(max_items)
    except (TypeError, ValueError):
        cap = 0
    if cap <= 0:
        return []

    shown = {_int_or_none(s) for s in (shown_story_ids or ())}
    shown.discard(None)

    mh: dict = {}
    if mute_hits:
        for sid, term in mute_hits.items():
            k = _int_or_none(sid)
            if k is None:
                continue
            mh[k] = term

    fh: set = set()
    if filter_hits:
        for sid in filter_hits:
            k = _int_or_none(sid)
            if k is not None:
                fh.add(k)

    candidates: list[dict] = []
    for row in (big_stories or ()):
        sid = _int_or_none(row.get("story_id"))
        if sid is None:
            continue
        if sid in shown:
            continue
        try:
            outlets = int(row.get("outlet_count"))
        except (TypeError, ValueError):
            continue
        if sid in mh:
            reason = REASON_MUTED
        elif sid in fh:
            reason = REASON_FILTERED
        else:
            reason = REASON_LOW_RELEVANCE
        candidates.append({
            "story_id": sid,
            "outlet_count": outlets,
            "hidden_reason": reason,
            "mute_term": mh.get(sid) if reason == REASON_MUTED else None,
        })

    candidates.sort(
        key=lambda r: (-r["outlet_count"], r["story_id"])
    )
    return candidates[:cap]


def _int_or_none(value) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
