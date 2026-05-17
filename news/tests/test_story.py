"""Tests for the story dossier blueprint (/story/<id>).

We stub `query` and `execute` so the route can be driven without a real
DB. Framing (LLM call) is monkeypatched to either succeed, fail with
LLMUnavailable, or be skipped depending on the test.
"""
import datetime as dt

import pytest

from app import create_app
from app.routes import story as story_mod
from app.classifier import LLMUnavailable


def _article(id_, *, source_id, source_name, source_lean, lean, title,
             summary="", body=None, category="general",
             published=dt.datetime(2026, 5, 13, 12, 0, 0)):
    return {
        "id": id_,
        "title": title,
        "url": f"https://x/{id_}",
        "summary": summary,
        "thumbnail_url": None,
        "byline": None,
        "published_at": published,
        "source_id": source_id,
        "source_name": source_name,
        "source_lean": source_lean,
        "political_lean": lean,
        "objectivity": 0.8,
        "category": category,
        "body_text": body,
    }


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr("app.db.close_conn", lambda exc=None: None)
    return create_app()


@pytest.fixture
def store(monkeypatch):
    """Scripted query responses + captured executes / dossier table."""
    state = {
        "canonical": {"id": 100, "story_id": 100},
        "members": [],
        "dossier_row": None,
        "executed": [],
    }

    def fake_query(sql, params=None, one=False):
        s = " ".join(sql.split()).lower()
        if "from articles where id =" in s:
            return state["canonical"]
        if "from story_dossiers where story_id" in s:
            return state["dossier_row"]
        if "from articles a" in s and "join sources s" in s and "story_id =" in s:
            return state["members"]
        if one:
            return None
        return []

    def fake_execute(sql, params=None):
        state["executed"].append((sql, params))
        s = " ".join(sql.split()).lower()
        if s.startswith("insert into story_dossiers"):
            story_id, sig, summary, count, buckets, model = params
            state["dossier_row"] = {
                "summary_text": summary,
                "member_signature": sig,
            }
        return 1

    class FakeConn:
        def commit(self):
            pass

    monkeypatch.setattr("app.routes.story.query", fake_query)
    monkeypatch.setattr("app.routes.story.execute", fake_execute)
    monkeypatch.setattr("app.routes.story.get_conn", lambda: FakeConn())
    monkeypatch.setattr("app.discussion.query", lambda sql, params=None, one=False: [])
    return state


@pytest.fixture
def client(app):
    return app.test_client()


def test_unknown_story_returns_404(client, store):
    store["canonical"] = None
    r = client.get("/story/999")
    assert r.status_code == 404


def test_non_canonical_member_returns_404(client, store):
    store["canonical"] = {"id": 100, "story_id": 200}
    r = client.get("/story/100")
    assert r.status_code == 404


def test_singleton_cluster_returns_404(client, store):
    store["members"] = [
        _article(100, source_id=1, source_name="Solo", source_lean=0.0, lean=0.0, title="Only"),
    ]
    r = client.get("/story/100")
    assert r.status_code == 404


def test_two_member_cluster_renders_without_framing(monkeypatch, client, store):
    store["members"] = [
        _article(100, source_id=1, source_name="LeftWeekly", source_lean=-0.6, lean=-0.5,
                 title="Headline A", summary="Lead from A " * 6),
        _article(101, source_id=2, source_name="RightDaily", source_lean=0.6, lean=0.5,
                 title="Headline B", summary="Lead from B " * 6),
    ]

    def _no_call(*a, **k):
        raise AssertionError("framing should not be generated below the threshold")
    monkeypatch.setattr(story_mod, "generate_framing", _no_call)

    r = client.get("/story/100")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Headline A" in body
    assert "Headline B" in body
    assert "LeftWeekly" in body and "RightDaily" in body
    assert "too small" in body or "queued" not in body


def test_three_member_two_buckets_generates_framing_and_caches(monkeypatch, client, store):
    store["members"] = [
        _article(100, source_id=1, source_name="LeftWeekly", source_lean=-0.6, lean=-0.5,
                 title="A", summary="Long enough lead paragraph from A. " * 3),
        _article(101, source_id=2, source_name="RightDaily", source_lean=0.6, lean=0.5,
                 title="B", summary="Long enough lead paragraph from B. " * 3),
        _article(102, source_id=3, source_name="WireService", source_lean=0.0, lean=0.0,
                 title="C", summary="Long enough lead paragraph from C. " * 3),
    ]
    calls = []

    def _fake_framing(members, *, api_key, model, **kwargs):
        calls.append(len(members))
        return {"summary": "FRAMING-OK", "usage": {"model": model}}

    monkeypatch.setattr(story_mod, "generate_framing", _fake_framing)

    r = client.get("/story/100")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "FRAMING-OK" in body
    assert calls == [3]
    inserts = [e for e in store["executed"] if "story_dossiers" in e[0].lower()]
    assert len(inserts) == 1
    assert store["dossier_row"]["summary_text"] == "FRAMING-OK"


def test_framing_cache_hit_by_signature_avoids_llm(monkeypatch, client, store):
    """If the cached signature matches the live member set, no LLM call."""
    store["members"] = [
        _article(100, source_id=1, source_name="L", source_lean=-0.6, lean=-0.5, title="A"),
        _article(101, source_id=2, source_name="R", source_lean=0.6, lean=0.5, title="B"),
        _article(102, source_id=3, source_name="C", source_lean=0.0, lean=0.0, title="C"),
    ]
    sig = story_mod._member_signature(store["members"])
    store["dossier_row"] = {"summary_text": "CACHED-SUMMARY", "member_signature": sig}

    def _no_call(*a, **k):
        raise AssertionError("LLM must not be invoked on cache hit")
    monkeypatch.setattr(story_mod, "generate_framing", _no_call)

    r = client.get("/story/100")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "CACHED-SUMMARY" in body


def test_framing_cache_miss_when_signature_changes(monkeypatch, client, store):
    store["members"] = [
        _article(100, source_id=1, source_name="L", source_lean=-0.6, lean=-0.5, title="A"),
        _article(101, source_id=2, source_name="R", source_lean=0.6, lean=0.5, title="B"),
        _article(102, source_id=3, source_name="C", source_lean=0.0, lean=0.0, title="C"),
    ]
    store["dossier_row"] = {
        "summary_text": "STALE-SUMMARY",
        "member_signature": "deadbeef-not-matching",
    }
    calls = []

    def _fake_framing(members, *, api_key, model, **kwargs):
        calls.append(True)
        return {"summary": "FRESH-SUMMARY", "usage": {"model": model}}

    monkeypatch.setattr(story_mod, "generate_framing", _fake_framing)
    r = client.get("/story/100")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "FRESH-SUMMARY" in body
    assert "STALE-SUMMARY" not in body
    assert calls == [True]


def test_llm_unavailable_renders_page_without_summary(monkeypatch, client, store):
    store["members"] = [
        _article(100, source_id=1, source_name="L", source_lean=-0.6, lean=-0.5, title="A"),
        _article(101, source_id=2, source_name="R", source_lean=0.6, lean=0.5, title="B"),
        _article(102, source_id=3, source_name="C", source_lean=0.0, lean=0.0, title="C"),
    ]

    def _fail(*a, **k):
        raise LLMUnavailable("no api key")
    monkeypatch.setattr(story_mod, "generate_framing", _fail)

    r = client.get("/story/100")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "queued" in body
    inserts = [e for e in store["executed"] if "story_dossiers" in e[0].lower()]
    assert inserts == []


def test_buckets_grouped_by_lean_threshold():
    """Sanity-check the bucket boundaries match the documented thresholds."""
    assert story_mod._lean_bucket(-0.25) == "left"
    assert story_mod._lean_bucket(-0.2) == "left"
    assert story_mod._lean_bucket(-0.1) == "center"
    assert story_mod._lean_bucket(0.0) == "center"
    assert story_mod._lean_bucket(0.19) == "center"
    assert story_mod._lean_bucket(0.2) == "right"
    assert story_mod._lean_bucket(0.5) == "right"
    assert story_mod._lean_bucket(None) == "center"


def test_member_signature_stable_for_set_not_order():
    sig1 = story_mod._member_signature([{"id": 3}, {"id": 1}, {"id": 2}])
    sig2 = story_mod._member_signature([{"id": 1}, {"id": 2}, {"id": 3}])
    sig3 = story_mod._member_signature([{"id": 1}, {"id": 2}, {"id": 4}])
    assert sig1 == sig2
    assert sig1 != sig3


def test_lead_paragraph_prefers_body(monkeypatch):
    body = "  short  \nThis is a much longer paragraph from the body text.\nNext one."
    assert story_mod._lead_paragraph(body, "fallback").startswith("This is a much longer")


def test_lead_paragraph_falls_back_to_summary():
    assert story_mod._lead_paragraph(None, "the rss summary") == "the rss summary"
    assert story_mod._lead_paragraph("", "the rss summary") == "the rss summary"
    assert story_mod._lead_paragraph(None, None) == ""


def test_single_bucket_cluster_skips_framing(monkeypatch, client, store):
    """3 members but all in the same bucket -> framing eligibility fails."""
    store["members"] = [
        _article(100, source_id=1, source_name="L1", source_lean=-0.7, lean=-0.6, title="A"),
        _article(101, source_id=2, source_name="L2", source_lean=-0.6, lean=-0.5, title="B"),
        _article(102, source_id=3, source_name="L3", source_lean=-0.5, lean=-0.4, title="C"),
    ]

    def _no_call(*a, **k):
        raise AssertionError("framing should not be generated for single-bucket clusters")
    monkeypatch.setattr(story_mod, "generate_framing", _no_call)

    r = client.get("/story/100")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "too small" in body


# --- /story/<id>/peek (across-the-spectrum in-feed) ---------------------

def test_peek_unknown_story_returns_404(client, store):
    store["canonical"] = None
    assert client.get("/story/999/peek").status_code == 404


def test_peek_non_canonical_member_returns_404(client, store):
    store["canonical"] = {"id": 100, "story_id": 200}
    assert client.get("/story/100/peek").status_code == 404


def test_peek_singleton_cluster_returns_404(client, store):
    store["members"] = [
        _article(100, source_id=1, source_name="Solo", source_lean=0.0, lean=0.0, title="Only"),
    ]
    assert client.get("/story/100/peek").status_code == 404


def test_peek_renders_sibling_angles_excluding_the_card_article(client, store):
    store["members"] = [
        _article(100, source_id=1, source_name="LeftWeekly", source_lean=-0.6,
                 lean=-0.5, title="Canonical headline"),
        _article(101, source_id=2, source_name="RightDaily", source_lean=0.6,
                 lean=0.5, title="Right take", summary="Right lead. " * 6),
        _article(102, source_id=3, source_name="WireService", source_lean=0.0,
                 lean=0.0, title="Wire take", summary="Wire lead. " * 6),
    ]
    r = client.get("/story/100/peek")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Across the spectrum" in body
    assert "RightDaily" in body and "WireService" in body
    assert "Right take" in body and "Wire take" in body
    # the card's own article must not be echoed back inside its peek
    assert "Canonical headline" not in body
    # deep-dive link to the full dossier is present
    assert '/story/100"' in body
    assert "Full dossier" in body


def test_peek_partial_has_no_base_chrome(client, store):
    store["members"] = [
        _article(100, source_id=1, source_name="A", source_lean=-0.5, lean=-0.5, title="A"),
        _article(101, source_id=2, source_name="B", source_lean=0.5, lean=0.5, title="B"),
    ]
    body = client.get("/story/100/peek").get_data(as_text=True)
    assert "<nav class=\"topnav\"" not in body
    assert "<!doctype html>" not in body.lower()
