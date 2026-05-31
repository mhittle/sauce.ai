"""Pure tests for the 3-bullet TL;DR helpers (no Flask / no DB).

Covers the two trust boundaries: sanitize_bullets (untrusted LLM output on
the write side) and parse_bullets (stored JSON on the read side), plus the
no-key / empty-input contract of summarize_batch_llm and prompt rendering.
DB- and route-level behavior is exercised in CI (sandbox has no MySQL).
"""
import json

import pytest

from app.article_summary import parse_bullets
from app.classifier import summarize_batch_llm
from app.classifier.llm import LLMUnavailable
from app.classifier.summary import (
    MAX_BULLETS,
    MAX_BULLET_CHARS,
    render_articles_block,
    sanitize_bullets,
)


def test_no_api_key_raises():
    with pytest.raises(LLMUnavailable):
        summarize_batch_llm("", "claude-haiku-4-5-20251001",
                            [(1, "title", "body text here")])


def test_empty_items_returns_empty():
    res = summarize_batch_llm("anything", "claude-haiku-4-5-20251001", [])
    assert res == {"by_id": {}, "usage": {}}


def test_sanitize_caps_count():
    out = sanitize_bullets(["a", "b", "c", "d", "e"])
    assert out == ["a", "b", "c"]
    assert len(out) <= MAX_BULLETS


def test_sanitize_trims_length_and_whitespace():
    long = "x" * (MAX_BULLET_CHARS + 50)
    out = sanitize_bullets(["  spaced\n\tout  ", long])
    assert out[0] == "spaced out"
    assert len(out[1]) == MAX_BULLET_CHARS


def test_sanitize_drops_empty_and_nonstring():
    out = sanitize_bullets(["", "   ", 42, None, {"x": 1}, "real"])
    assert out == ["real"]


def test_sanitize_non_list_returns_empty():
    assert sanitize_bullets(None) == []
    assert sanitize_bullets("not a list") == []
    assert sanitize_bullets(123) == []


def test_parse_bullets_roundtrips_sanitized_json():
    stored = json.dumps(["First point.", "Second point.", "Third point."])
    assert parse_bullets(stored) == ["First point.", "Second point.", "Third point."]


def test_parse_bullets_tolerates_garbage():
    assert parse_bullets(None) == []
    assert parse_bullets("") == []
    assert parse_bullets("{not json") == []
    assert parse_bullets(json.dumps("a string")) == []
    assert parse_bullets(json.dumps({"k": "v"})) == []


def test_parse_bullets_reclamps_oversized_stored_data():
    # Even if a bad/old row stored >MAX_BULLETS, the reader clamps.
    stored = json.dumps(["1", "2", "3", "4", "5"])
    assert len(parse_bullets(stored)) == MAX_BULLETS


def test_render_articles_block_caps_body_and_formats():
    block = render_articles_block([(7, "A Title", "word " * 100)], max_body_chars=20)
    assert "id: 7" in block
    assert "title: A Title" in block
    body_line = [ln for ln in block.splitlines() if ln.startswith("body: ")][0]
    assert len(body_line) - len("body: ") <= 20


def test_render_articles_block_handles_none_body():
    block = render_articles_block([(1, "T", None)])
    assert "body: " in block
