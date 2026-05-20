from app.classifier import classify_batch_llm, LLMUnavailable
from app.classifier.llm import LLM_PERCEPTION_KEYS, LLM_PERCEPTION_DEFAULT
import pytest


def test_no_api_key_raises():
    with pytest.raises(LLMUnavailable):
        classify_batch_llm("", "claude-haiku-4-5-20251001",
                           [(1, "S", 0.0, "title", "summary")])


def test_empty_articles_returns_empty():
    res = classify_batch_llm("anything", "claude-haiku-4-5-20251001", [])
    assert res == {"by_id": {}, "usage": {}}


def test_perception_keys_constant_shape():
    assert len(LLM_PERCEPTION_KEYS) == 6
    assert set(LLM_PERCEPTION_KEYS) == {
        "tone_calmness", "sensationalism", "analysis_depth",
        "emotional_charge", "hedging", "solution_orientation",
    }
    assert 0.0 <= LLM_PERCEPTION_DEFAULT <= 1.0
