"""Unit tests for app/discussion.py.

`discussion_label` and `_merge` are pure. `discussions_for_articles` and
`discussions_for_story` hit the DB via `query`; we monkeypatch
`app.discussion.query` with a fake that returns scripted rows (same pattern
as test_story.py).
"""
import app.discussion as disc


def _row(article_id, source, comments, permalink, subreddit=None):
    return {
        "article_id": article_id,
        "source": source,
        "comments": comments,
        "permalink": permalink,
        "subreddit": subreddit,
    }


def test_label_hn():
    assert disc.discussion_label("hn", None) == "Hacker News"


def test_label_reddit_with_subreddit():
    assert disc.discussion_label("reddit", "technology") == "r/technology"


def test_label_reddit_without_subreddit():
    assert disc.discussion_label("reddit", None) == "Reddit"


def test_label_unknown_passthrough():
    assert disc.discussion_label("mastodon", None) == "mastodon"


def test_discussions_for_articles_empty_input_skips_query(monkeypatch):
    def boom(*a, **k):  # query must not be called for an empty id list
        raise AssertionError("query should not run for empty input")

    monkeypatch.setattr(disc, "query", boom)
    assert disc.discussions_for_articles([]) == {}


def test_discussions_for_articles_groups_and_sorts(monkeypatch):
    rows = [
        _row(1, "reddit", 12, "https://www.reddit.com/r/news/x", "news"),
        _row(1, "hn", 88, "https://news.ycombinator.com/item?id=1"),
        _row(2, "hn", 3, "https://news.ycombinator.com/item?id=2"),
    ]
    monkeypatch.setattr(disc, "query", lambda sql, params=None, one=False: rows)

    out = disc.discussions_for_articles([1, 2])

    assert set(out) == {1, 2}
    # article 1: HN (88) sorts before r/news (12)
    assert [e["label"] for e in out[1]] == ["Hacker News", "r/news"]
    assert out[1][0] == {
        "label": "Hacker News",
        "comments": 88,
        "url": "https://news.ycombinator.com/item?id=1",
    }
    assert out[2][0]["label"] == "Hacker News"


def test_discussions_for_articles_missing_id_absent(monkeypatch):
    monkeypatch.setattr(
        disc, "query",
        lambda sql, params=None, one=False: [_row(5, "hn", 1, "u")],
    )
    out = disc.discussions_for_articles([5, 6])
    assert 6 not in out
    assert out.get(6, []) == []


def test_merge_dedupes_by_url_keeps_max_comments():
    rows = [
        _row(1, "hn", 10, "https://news.ycombinator.com/item?id=9"),
        _row(2, "hn", 42, "https://news.ycombinator.com/item?id=9"),
    ]
    merged = disc._merge(rows)
    assert len(merged) == 1
    assert merged[0]["comments"] == 42


def test_merge_sorts_by_comments_desc():
    rows = [
        _row(1, "reddit", 5, "a", "news"),
        _row(1, "hn", 50, "b"),
        _row(1, "reddit", 20, "c", "science"),
    ]
    merged = disc._merge(rows)
    assert [e["comments"] for e in merged] == [50, 20, 5]


def test_discussions_for_story_empty_input_skips_query(monkeypatch):
    monkeypatch.setattr(
        disc, "query",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no query")),
    )
    assert disc.discussions_for_story([]) == []


def test_discussions_for_story_merges_cluster(monkeypatch):
    # Same HN thread matched against two cluster members (syndicated reprint)
    # plus a distinct Reddit thread on one member.
    rows = [
        _row(1, "hn", 30, "https://news.ycombinator.com/item?id=7"),
        _row(2, "hn", 30, "https://news.ycombinator.com/item?id=7"),
        _row(2, "reddit", 9, "https://www.reddit.com/r/tech/y", "tech"),
    ]
    monkeypatch.setattr(disc, "query", lambda sql, params=None, one=False: rows)

    merged = disc.discussions_for_story([1, 2])

    urls = [e["url"] for e in merged]
    assert urls == [
        "https://news.ycombinator.com/item?id=7",
        "https://www.reddit.com/r/tech/y",
    ]
    assert len(merged) == 2
    assert merged[0]["label"] == "Hacker News"
    assert merged[1]["label"] == "r/tech"
