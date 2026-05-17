"""Pure helpers for the external-trending signal.

Kept Flask-free so the `trending_poll` cron job and the unit tests can
import them without spinning up the app or touching the DB. Mirrors the
pattern used by `app.discovery`, `app.feed_validation`, and
`app.language`.

The signal answers: "is this article about a topic that's trending in
the news at large right now?" We harvest two external, no-API-key feeds:

- Google Trends daily trending-searches RSS — explicit trending query
  terms, optionally with an approximate search-traffic number.
- Google News RSS (top stories + a few topic sections) — the headlines
  Google is currently surfacing broadly.

Both reduce to a set of weighted *topics* (token bags + a 0..1 heat).
An article scores by how much of a hot topic's vocabulary it contains,
scaled by that topic's heat. No URL matching: Google News RSS links are
opaque `news.google.com` redirects, not publisher URLs, so topic/keyword
overlap is the only honest signal here (and is exactly what "trending
topics" means). Heavy-paraphrase / synonym matching is a documented v1
limitation — improves once entity extraction lands (see roadmap).
"""
from __future__ import annotations

import math
import re
from typing import Optional


# Common words that carry no topical signal. Deliberately small — the
# token-overlap math already down-weights generic words because a topic
# has to share *its* vocabulary, and headline boilerplate is stripped
# separately.
STOPWORDS = frozenset(
    """
    the a an and or but if then else of to in on at by for with from as is are
    was were be been being it its this that these those new news latest update
    updates live say says said report reports amid over after before into out
    up down off about more most than how why what when where who which will
    can could would should may might just also not no yes vs via per
    """.split()
)

_WORD_RE = re.compile(r"[a-z0-9]+")


def normalize_text(s: Optional[str]) -> str:
    return (s or "").strip().lower()


def tokenize(s: Optional[str]) -> frozenset:
    """Significant lowercase tokens: alphanumeric, length >= 3, non-stopword.

    Returned as a set — within-text repetition shouldn't inflate overlap.
    """
    out = set()
    for tok in _WORD_RE.findall(normalize_text(s)):
        if len(tok) >= 3 and tok not in STOPWORDS:
            out.add(tok)
    return frozenset(out)


def _strip_gnews_source(title: str) -> str:
    """Google News titles are "Headline text - Publisher". Drop the
    trailing " - Publisher" so the publisher name doesn't pollute the
    topic vocabulary."""
    if " - " in title:
        head, _, tail = title.rpartition(" - ")
        if head.strip():
            return head.strip()
    return title.strip()


def _approx_traffic(entry) -> Optional[int]:
    """Google Trends daily RSS carries <ht:approx_traffic>200,000+</...>.
    feedparser exposes it under varying keys depending on version; probe
    the likely ones and parse the leading integer."""
    for key in ("ht_approx_traffic", "approx_traffic", "approx_traffic_detail"):
        v = entry.get(key) if isinstance(entry, dict) else getattr(entry, key, None)
        if not v:
            continue
        m = re.search(r"[\d,]+", str(v))
        if m:
            try:
                return int(m.group(0).replace(",", ""))
            except ValueError:
                pass
    return None


def parse_trends_rss(content, *, max_terms: int = 40) -> list:
    """Parse Google Trends daily-trends RSS bytes into
    [{"term": str, "traffic": int|None, "rank": i}, ...]."""
    import feedparser  # lazy: sandbox can't always build feedparser

    parsed = feedparser.parse(content)
    out = []
    for i, e in enumerate(parsed.entries[:max_terms]):
        term = (e.get("title") if isinstance(e, dict) else getattr(e, "title", "")) or ""
        term = term.strip()
        if not term:
            continue
        out.append({"term": term, "traffic": _approx_traffic(e), "rank": i})
    return out


def parse_gnews_rss(content, *, max_items: int = 40) -> list:
    """Parse Google News RSS bytes into [{"headline": str, "rank": i}, ...]
    with the trailing " - Publisher" stripped from each title."""
    import feedparser  # lazy

    parsed = feedparser.parse(content)
    out = []
    for i, e in enumerate(parsed.entries[:max_items]):
        title = (e.get("title") if isinstance(e, dict) else getattr(e, "title", "")) or ""
        headline = _strip_gnews_source(title)
        if headline:
            out.append({"headline": headline, "rank": i})
    return out


def _rank_heat(rank: int, total: int) -> float:
    """Linear positional heat: #1 ~= 1.0, last ~= small but non-zero."""
    if total <= 1:
        return 1.0
    return 1.0 - (rank / total) * 0.85


def _traffic_heat(traffic: int) -> float:
    """Log-scale an approximate search-traffic count to 0..1. ~2M+ caps
    at 1.0; 1k floors near 0.15."""
    return max(0.0, min(1.0, math.log1p(traffic) / math.log1p(2_000_000)))


# Google Trends terms are an explicit trending signal; Google News
# headlines are noisier (any top story, trending or not), so weight them
# slightly lower when both name the same topic.
_TRENDS_WEIGHT = 1.0
_GNEWS_WEIGHT = 0.8


def build_topic_index(trends: list, gnews: list, *, min_tokens: int = 1) -> list:
    """Combine parsed Trends terms + GNews headlines into a topic list:
    [{"tokens": frozenset, "heat": float, "label": str}, ...].

    Heat is 0..1. Topics whose vocabulary is entirely stopwords (no
    usable tokens) are dropped.
    """
    topics = []
    n_tr = len(trends)
    for t in trends:
        toks = tokenize(t["term"])
        if len(toks) < min_tokens:
            continue
        if t.get("traffic"):
            heat = _traffic_heat(t["traffic"])
        else:
            heat = _rank_heat(t["rank"], n_tr)
        topics.append({"tokens": toks, "heat": min(1.0, heat * _TRENDS_WEIGHT),
                        "label": t["term"]})

    n_gn = len(gnews)
    for gentry in gnews:
        toks = tokenize(gentry["headline"])
        if len(toks) < min_tokens:
            continue
        heat = _rank_heat(gentry["rank"], n_gn) * _GNEWS_WEIGHT
        topics.append({"tokens": toks, "heat": min(1.0, heat),
                       "label": gentry["headline"]})
    return topics


def score_article(title, summary, topic_index, *, summary_chars: int = 240) -> float:
    """0..1: strength of this article's best match to any hot topic.

    For each topic: fraction of the topic's tokens present in the
    article (title + summary lead), scaled by the topic's heat. The
    article's score is the max over all topics. Fraction-of-topic
    (rather than raw overlap count) means a fully-covered short topic
    ("solar eclipse") beats a partially-covered long one, and a single
    shared generic word can't fully light up a multi-word topic.
    """
    art_tokens = tokenize(title) | tokenize((summary or "")[:summary_chars])
    if not art_tokens:
        return 0.0
    best = 0.0
    for topic in topic_index:
        ttoks = topic["tokens"]
        if not ttoks:
            continue
        overlap = len(art_tokens & ttoks)
        if overlap == 0:
            continue
        frac = overlap / len(ttoks)
        s = frac * topic["heat"]
        if s > best:
            best = s
    return round(max(0.0, min(1.0, best)), 4)
