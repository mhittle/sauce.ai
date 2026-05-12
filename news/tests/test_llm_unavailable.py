from app.classifier import classify_batch_llm, LLMUnavailable
import pytest


def test_no_api_key_raises():
    with pytest.raises(LLMUnavailable):
        classify_batch_llm("", "claude-haiku-4-5-20251001",
                           [(1, "S", 0.0, "title", "summary")])


def test_empty_articles_returns_empty():
    res = classify_batch_llm("anything", "claude-haiku-4-5-20251001", [])
    assert res == {"by_id": {}, "usage": {}}
