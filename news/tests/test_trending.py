"""Unit tests for the external-trending helpers (BUG-015).

Exercises the pure functions in `app.trending`:
- `tokenize` / `normalize_text` — significant-token extraction
- `parse_trends_rss` / `parse_gnews_rss` — RSS shaping against a stubbed
  feedparser (the CI sandbox can't build feedparser/sgmllib3k)
- `build_topic_index` — heat assignment + stopword-only topic drop
- `score_article` — topic-overlap scoring, heat scaling, clamping

The `trending_poll` cron entrypoint is not exercised here; its behavior
is covered indirectly via these pure helpers (same convention as
test_discovery.py).
"""
import sys
import types

import pytest


@pytest.fixture(autouse=True)
def _stub_feedparser(monkeypatch):
    """Stub feedparser so the lazy import in app.trending resolves.
    Tests drive parsing by setting state["entries"]."""
    stub = types.ModuleType("feedparser")
    state = {"entries": []}

    def _parse(_content):
        return types.SimpleNamespace(entries=list(state["entries"]))

    stub.parse = _parse
    monkeypatch.setitem(sys.modules, "feedparser", stub)
    return state


from app.trending import (  # noqa: E402
    tokenize,
    normalize_text,
    parse_trends_rss,
    parse_gnews_rss,
    build_topic_index,
    score_article,
    topic_key,
    topic_matches,
    build_persist_rows,
    group_topic_stories,
)


# ---------------------------------------------------------------------------
# tokenize / normalize_text
# ---------------------------------------------------------------------------

def test_tokenize_drops_short_and_stopwords_and_lowercases():
    toks = tokenize("The NEW Solar Eclipse over Texas")
    assert "solar" in toks and "eclipse" in toks and "texas" in toks
    assert "the" not in toks and "new" not in toks  # stopwords
    assert "of" not in toks


def test_tokenize_handles_punctuation_and_empty():
    assert tokenize(None) == frozenset()
    assert tokenize("   ") == frozenset()
    assert tokenize("U.S.-China trade-war!") == frozenset({"china", "trade", "war"})


def test_normalize_text_trims_and_lowercases():
    assert normalize_text("  HeLLo  ") == "hello"
    assert normalize_text(None) == ""


# ---------------------------------------------------------------------------
# parse_trends_rss
# ---------------------------------------------------------------------------

def test_parse_trends_rss_extracts_term_and_traffic(_stub_feedparser):
    _stub_feedparser["entries"] = [
        {"title": "solar eclipse", "ht_approx_traffic": "500,000+"},
        {"title": "election results"},  # no traffic key
    ]
    out = parse_trends_rss(b"<rss/>")
    assert out[0]["term"] == "solar eclipse"
    assert out[0]["traffic"] == 500000
    assert out[0]["rank"] == 0
    assert out[1]["traffic"] is None
    assert out[1]["rank"] == 1


def test_parse_trends_rss_skips_blank_titles(_stub_feedparser):
    _stub_feedparser["entries"] = [{"title": "  "}, {"title": "mars rover"}]
    out = parse_trends_rss(b"x")
    assert len(out) == 1 and out[0]["term"] == "mars rover"


# ---------------------------------------------------------------------------
# parse_gnews_rss
# ---------------------------------------------------------------------------

def test_parse_gnews_rss_strips_publisher_suffix(_stub_feedparser):
    _stub_feedparser["entries"] = [
        {"title": "Fed holds interest rates steady - Reuters"},
        {"title": "No dash headline"},
    ]
    out = parse_gnews_rss(b"x")
    assert out[0]["headline"] == "Fed holds interest rates steady"
    assert out[0]["rank"] == 0
    assert out[1]["headline"] == "No dash headline"


def test_parse_gnews_rss_keeps_headline_when_only_suffix(_stub_feedparser):
    # " - X" with empty head must not collapse to empty.
    _stub_feedparser["entries"] = [{"title": " - JustASource"}]
    out = parse_gnews_rss(b"x")
    assert out[0]["headline"] == "- JustASource"


# ---------------------------------------------------------------------------
# build_topic_index
# ---------------------------------------------------------------------------

def test_build_topic_index_assigns_heat_and_keeps_labels():
    trends = [{"term": "solar eclipse", "traffic": 2_000_000, "rank": 0}]
    gnews = [{"headline": "Federal Reserve holds rates", "rank": 0}]
    topics = build_topic_index(trends, gnews)
    assert len(topics) == 2
    by_label = {t["label"]: t for t in topics}
    assert "solar" in by_label["solar eclipse"]["tokens"]
    for t in topics:
        assert 0.0 <= t["heat"] <= 1.0
    # High-traffic trend should be hotter than a mid-rank gnews headline.
    assert by_label["solar eclipse"]["heat"] > by_label["Federal Reserve holds rates"]["heat"]


def test_build_topic_index_drops_stopword_only_topics():
    trends = [{"term": "the of and", "traffic": None, "rank": 0}]
    gnews = [{"headline": "is it new", "rank": 0}]
    assert build_topic_index(trends, gnews) == []


def test_build_topic_index_traffic_beats_rank_for_low_rank_trend():
    trends = [{"term": "alpha beta", "traffic": 1_500_000, "rank": 9}]
    topics = build_topic_index(trends, [])
    assert topics[0]["heat"] > 0.5  # traffic-driven, not crushed by rank 9


# ---------------------------------------------------------------------------
# score_article
# ---------------------------------------------------------------------------

def _topics():
    return build_topic_index(
        [{"term": "solar eclipse", "traffic": 2_000_000, "rank": 0}],
        [{"headline": "Federal Reserve interest rate decision", "rank": 0}],
    )


def test_score_article_full_match_scores_high():
    s = score_article("Total solar eclipse wows millions", "", _topics())
    assert s > 0.8


def test_score_article_no_overlap_scores_zero():
    s = score_article("Local bakery wins award", "A small shop in Maine", _topics())
    assert s == 0.0


def test_score_article_partial_topic_match_is_scaled_down():
    full = score_article("Federal Reserve interest rate decision today", "", _topics())
    partial = score_article("Reserve players join the squad", "", _topics())
    assert partial < full
    assert 0.0 < partial < 1.0


def test_score_article_uses_summary_lead_when_title_misses():
    s = score_article("Sky watchers gather", "Crowds turned out for the solar eclipse",
                       _topics())
    assert s > 0.0


def test_score_article_empty_inputs_safe():
    assert score_article("", "", _topics()) == 0.0
    assert score_article(None, None, _topics()) == 0.0
    assert score_article("anything", "", []) == 0.0


def test_score_article_clamped_0_1():
    s = score_article("solar eclipse solar eclipse", "solar eclipse", _topics())
    assert 0.0 <= s <= 1.0


# ---------------------------------------------------------------------------
# build_topic_index now tags origin
# ---------------------------------------------------------------------------

def test_build_topic_index_tags_origin():
    topics = build_topic_index(
        [{"term": "solar eclipse", "traffic": 2_000_000, "rank": 0}],
        [{"headline": "Federal Reserve holds rates", "rank": 0}],
    )
    by_label = {t["label"]: t for t in topics}
    assert by_label["solar eclipse"]["origin"] == "trends"
    assert by_label["Federal Reserve holds rates"]["origin"] == "gnews"


# ---------------------------------------------------------------------------
# topic_key
# ---------------------------------------------------------------------------

def test_topic_key_is_order_independent_and_stable():
    k1 = topic_key(tokenize("Fed holds rates steady"))
    k2 = topic_key(tokenize("steady rates holds Fed"))
    assert k1 == k2
    assert len(k1) == 40  # sha1 hex


def test_topic_key_differs_for_different_vocab():
    assert topic_key(frozenset({"solar", "eclipse"})) != topic_key(
        frozenset({"federal", "reserve"})
    )


def test_topic_key_collapses_near_duplicate_headlines():
    # The two GNews headlines share the same significant tokens once
    # stopwords/short tokens are dropped -> one trending topic.
    a = topic_key(tokenize("The Fed holds rates"))
    b = topic_key(tokenize("Fed holds rates"))
    assert a == b


# ---------------------------------------------------------------------------
# topic_matches
# ---------------------------------------------------------------------------

def test_topic_matches_max_equals_score_article():
    topics = _topics()
    title = "Federal Reserve interest rate decision and solar eclipse"
    matches = topic_matches(title, "", topics)
    assert matches  # overlaps both topics
    assert max(s for _, s in matches) == score_article(title, "", topics)


def test_topic_matches_empty_when_no_overlap_or_no_tokens():
    assert topic_matches("Local bakery wins award", "", _topics()) == []
    assert topic_matches("", "", _topics()) == []
    assert topic_matches("anything here", "", []) == []


def test_topic_matches_only_returns_positive_scores():
    for _, s in topic_matches("solar eclipse over Texas", "", _topics()):
        assert s > 0.0


# ---------------------------------------------------------------------------
# build_persist_rows
# ---------------------------------------------------------------------------

def test_build_persist_rows_basic_shaping():
    topics = build_topic_index(
        [{"term": "solar eclipse", "traffic": 2_000_000, "rank": 0}],
        [{"headline": "Federal Reserve interest rate decision", "rank": 0}],
    )
    articles = [
        {"id": 1, "title": "Total solar eclipse wows millions", "summary": ""},
        {"id": 2, "title": "Federal Reserve interest rate decision today", "summary": ""},
        {"id": 3, "title": "Local bakery wins award", "summary": ""},
    ]
    topic_rows, match_rows = build_persist_rows(topics, articles)

    assert len(topic_rows) == 2
    for k, label, origin, heat in topic_rows:
        assert len(k) == 40
        assert origin in ("trends", "gnews")
        assert 0.0 <= heat <= 1.0

    matched_articles = {aid for _, aid, _ in match_rows}
    assert matched_articles == {1, 2}  # article 3 matches nothing
    for _, _, s in match_rows:
        assert s > 0.0


def test_build_persist_rows_collapses_duplicate_topic_keeping_max_heat():
    # Same vocabulary from a hot Trends term and a cooler GNews headline:
    # one persisted topic row, the higher heat wins.
    topics = build_topic_index(
        [{"term": "mars rover", "traffic": 2_000_000, "rank": 0}],
        [{"headline": "Mars rover", "rank": 30}],
    )
    articles = [{"id": 9, "title": "NASA Mars rover finds water", "summary": ""}]
    topic_rows, match_rows = build_persist_rows(topics, articles)

    assert len(topic_rows) == 1
    # one match row for the single (collapsed key, article) pair
    assert len(match_rows) == 1
    assert match_rows[0][1] == 9


def test_build_persist_rows_empty_inputs():
    assert build_persist_rows([], []) == ([], [])
    # Topics but no articles: every topic row, zero match rows.
    topic_rows, match_rows = build_persist_rows(_topics(), [])
    assert match_rows == []
    assert len(topic_rows) == 2


# ---------------------------------------------------------------------------
# group_topic_stories
# ---------------------------------------------------------------------------

def test_group_topic_stories_buckets_and_caps_per_topic():
    rows = [
        {"topic_key": "a", "story_id": 1},
        {"topic_key": "a", "story_id": 2},
        {"topic_key": "a", "story_id": 3},
        {"topic_key": "a", "story_id": 4},
        {"topic_key": "b", "story_id": 5},
    ]
    out = group_topic_stories(rows, per_topic=3)
    assert [r["story_id"] for r in out["a"]] == [1, 2, 3]  # 4 dropped (cap)
    assert [r["story_id"] for r in out["b"]] == [5]


def test_group_topic_stories_empty():
    assert group_topic_stories([]) == {}
