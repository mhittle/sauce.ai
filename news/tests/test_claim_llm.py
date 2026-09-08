"""Tests for the /claim model layer with a stubbed Anthropic client."""
import json
import sys
import types

import pytest

from app.classifier import claim_llm
from app.classifier import claim_prompts
from app.classifier.llm import LLMUnavailable
from app import claim


class _Usage:
    def __init__(self, i=100, o=50, c=0):
        self.input_tokens = i
        self.output_tokens = o
        self.cache_read_input_tokens = c


class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Resp:
    def __init__(self, text, stop_reason="end_turn"):
        self.content = [_Block(text)]
        self.usage = _Usage()
        self.stop_reason = stop_reason


class _BadRequest(Exception):
    pass


def _install_fake_anthropic(monkeypatch, replies, *, reject_output_config=False, raise_exc=None):
    """`replies` is a list of JSON-able payloads (or raw strings) returned in
    order. Records every `messages.create` call's kwargs."""
    calls = []

    class _Messages:
        def create(self, **kwargs):
            calls.append(kwargs)
            if raise_exc:
                raise raise_exc
            if reject_output_config and "output_config" in kwargs:
                raise _BadRequest("output_config not supported")
            reply = replies.pop(0)
            if isinstance(reply, _Resp):
                return reply
            return _Resp(reply if isinstance(reply, str) else json.dumps(reply))

    class _Client:
        def __init__(self, api_key=None):
            self.messages = _Messages()

    mod = types.ModuleType("anthropic")
    mod.Anthropic = _Client
    mod.BadRequestError = _BadRequest
    monkeypatch.setitem(sys.modules, "anthropic", mod)
    return calls


LOCATE_REPLY = {
    "claim": "Daily coffee cuts dementia risk by 40%",
    "claim_sentences": ["A new study in JAMA Neurology found...", "", 7],
    "mentions_study": True,
    "identifiers": {"doi": " 10.1001/jamaneurol.2024.1234 ", "pmid": None, "title": None,
                    "first_author": "Lee", "journal": "JAMA Neurology", "institution": None,
                    "year": "2024"},
    "source_kind": "news",
}


def test_locate_claim_parses_and_normalizes(monkeypatch):
    calls = _install_fake_anthropic(monkeypatch, [LOCATE_REPLY])
    out = claim_llm.locate_claim("key", "claude-haiku-4-5", "Coffee cuts dementia", "body " * 3000)
    assert out["claim"] == "Daily coffee cuts dementia risk by 40%"
    assert out["claim_sentences"] == ["A new study in JAMA Neurology found..."]
    assert out["identifiers"]["doi"] == "10.1001/jamaneurol.2024.1234"
    assert out["identifiers"]["year"] == 2024
    assert out["identifiers"]["pmid"] is None
    assert out["source_kind"] == "news"
    assert out["usage"]["model"] == "claude-haiku-4-5"
    assert out["usage"]["est_cost_usd"] > 0
    kw = calls[0]
    assert kw["output_config"]["format"]["schema"] is claim_prompts.LOCATE_SCHEMA
    assert kw["timeout"] == 30.0
    assert len(kw["messages"][0]["content"]) <= claim_prompts.MAX_BODY_CHARS + 200


def test_locate_claim_falls_back_when_structured_output_rejected(monkeypatch):
    calls = _install_fake_anthropic(monkeypatch, ["```json\n" + json.dumps(LOCATE_REPLY) + "\n```"],
                                    reject_output_config=True)
    out = claim_llm.locate_claim("key", "m", "h", "b")
    assert out["identifiers"]["journal"] == "JAMA Neurology"
    assert len(calls) == 2 and "output_config" not in calls[1]


def test_locate_claim_tolerates_junk_shape(monkeypatch):
    _install_fake_anthropic(monkeypatch, [{"claim": None, "identifiers": "nope", "source_kind": "x"}])
    out = claim_llm.locate_claim("key", "m", "The headline", "b")
    assert out["claim"] == "The headline"
    assert out["identifiers"]["doi"] is None
    assert out["source_kind"] == "unknown"
    assert out["mentions_study"] is False


def test_extract_evidence_returns_raw_fields_for_validation(monkeypatch):
    abstract = "We randomized 1,204 adults. Relative risk 0.62 (95% CI 0.48-0.81)."
    reply = {"design": {"value": "rct", "span": "We randomized"},
             "n": {"value": 1204, "span": "1,204 adults"},
             "effect": {"type": "RR", "point": 0.62, "ci_low": 0.48, "ci_high": 0.81,
                        "span": "Relative risk 0.62 (95% CI 0.48-0.81)"},
             "outcome": {"value": "stroke", "span": "primary outcome stroke"}}
    calls = _install_fake_anthropic(monkeypatch, [reply])
    out = claim_llm.extract_evidence("key", "claude-sonnet-5", abstract, title="T", journal="J")
    assert out["fields"] == reply
    assert out["usage"]["model"] == "claude-sonnet-5"
    assert calls[0]["max_tokens"] == 2048
    validated = claim.validate_spans(out["fields"], abstract)
    assert set(validated) == {"design", "n", "effect"}


def test_extract_evidence_rejects_empty_abstract(monkeypatch):
    _install_fake_anthropic(monkeypatch, [{}])
    with pytest.raises(LLMUnavailable):
        claim_llm.extract_evidence("key", "m", "   ")


def test_grade_concordance_parses(monkeypatch):
    reply = {"concordance": 1, "concordance_why": "Headline says cuts; abstract is a cohort.",
             "flags": [{"flag": "causal-language-on-observational", "why": "'cuts'"},
                       {"flag": "bogus", "why": "x"}]}
    calls = _install_fake_anthropic(monkeypatch, [reply])
    out = claim_llm.grade_concordance(
        "key", "m", headline="Coffee cuts dementia", claim="c", abstract="a",
        fields={"design": {"value": "cohort", "span": "x"}}, source_kind="news", excerpt="e")
    assert out["concordance"] == 1
    assert out["concordance_why"].startswith("Headline says")
    assert [f["flag"] for f in claim.merge_flags([], out["flags"])] == ["causal-language-on-observational"]
    assert "Study design (validated from the abstract): cohort" in calls[0]["messages"][0]["content"]
    assert "Species: not stated" in calls[0]["messages"][0]["content"]


def test_grade_concordance_out_of_range_is_none(monkeypatch):
    _install_fake_anthropic(monkeypatch, [{"concordance": 7, "flags": "no"}])
    out = claim_llm.grade_concordance("key", "m", headline="h", claim="c", abstract="a", fields={})
    assert out["concordance"] is None and out["flags"] == []


def test_no_api_key_raises():
    with pytest.raises(LLMUnavailable):
        claim_llm.locate_claim("", "m", "h", "b")


def test_api_exception_wrapped(monkeypatch):
    _install_fake_anthropic(monkeypatch, [], raise_exc=RuntimeError("boom"))
    with pytest.raises(LLMUnavailable):
        claim_llm.locate_claim("key", "m", "h", "b")


def test_refusal_stop_reason_is_unavailable(monkeypatch):
    _install_fake_anthropic(monkeypatch, [_Resp("{}", stop_reason="refusal")])
    with pytest.raises(LLMUnavailable):
        claim_llm.locate_claim("key", "m", "h", "b")


def test_parse_json_text_tolerance():
    assert claim_llm.parse_json_text('Sure: {"a": 1} done') == {"a": 1}
    assert claim_llm.parse_json_text('```json\n{"a": [1]}\n```') == {"a": [1]}
    with pytest.raises(LLMUnavailable):
        claim_llm.parse_json_text("no json here")
    with pytest.raises(LLMUnavailable):
        claim_llm.parse_json_text("[1, 2]")
    with pytest.raises(LLMUnavailable):
        claim_llm.parse_json_text("{bad json}")


def test_estimate_cost_by_model():
    u = _Usage(i=1_000_000, o=0, c=0)
    assert claim_llm.estimate_cost("claude-sonnet-5", u) == pytest.approx(2.0)
    assert claim_llm.estimate_cost("claude-sonnet-4-6", u) == pytest.approx(3.0)
    assert claim_llm.estimate_cost("claude-opus-5", u) == pytest.approx(5.0)
    assert claim_llm.estimate_cost("claude-haiku-4-5", u) == pytest.approx(1.0)


def test_schemas_are_strict_objects():
    for schema in (claim_prompts.LOCATE_SCHEMA, claim_prompts.EXTRACT_SCHEMA, claim_prompts.GRADE_SCHEMA):
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
    assert set(claim_prompts.MODEL_FLAGS) <= set(claim.SPIN_FLAGS)
    assert "no-study-located" not in claim_prompts.MODEL_FLAGS
    assert "grade" not in claim_prompts.GRADE_SCHEMA["properties"]
