"""Unit tests for the pure helpers behind "Ask your feed".

The Anthropic SDK is stubbed via `sys.modules` (same pattern as
`test_algo_nl.py`) so these run without the SDK; the production helper
imports it lazily.
"""
import json
import sys
import types

import pytest

from app import ask
from app.classifier import LLMUnavailable


def _install_fake_anthropic(monkeypatch, *, response_text=None, raise_on_create=None):
    class _Block:
        def __init__(self, t, text):
            self.type = t
            self.text = text

    class _Usage:
        input_tokens = 200
        output_tokens = 80
        cache_read_input_tokens = 0

    class _Resp:
        def __init__(self, text):
            self.content = [_Block("text", text)]
            self.usage = _Usage()

    captured = {"system": None, "messages": None, "model": None}

    class _Messages:
        def create(self, *, model, max_tokens, system, messages, timeout):
            if raise_on_create is not None:
                raise raise_on_create
            captured["model"] = model
            captured["system"] = system
            captured["messages"] = messages
            return _Resp(response_text)

    class _Client:
        def __init__(self, api_key=None):
            self.messages = _Messages()

    stub = types.ModuleType("anthropic")
    stub.Anthropic = _Client
    monkeypatch.setitem(sys.modules, "anthropic", stub)
    return captured


# ---------- query_terms ----------------------------------------------------


def test_query_terms_drops_interrogatives_and_stopwords():
    assert ask.query_terms("what happened with the budget bill this week?") \
        == "budget bill"


def test_query_terms_all_stopwords_yields_empty():
    assert ask.query_terms("what is going on?") == ""


def test_query_terms_dedupes_and_caps():
    s = " ".join(["climate"] * 5 + ["policy"] * 3 + [f"t{i}" for i in range(20)])
    out = ask.query_terms(s).split()
    assert out[:2] == ["climate", "policy"]
    # Each unique token appears once and the list is capped.
    assert len(out) <= 12
    assert len(out) == len(set(out))


def test_query_terms_handles_empty_and_none():
    assert ask.query_terms("") == ""
    assert ask.query_terms(None) == ""


def test_query_terms_keeps_proper_nouns_and_digits():
    out = ask.query_terms("Did the Fed announce a 2024 rate decision?")
    assert "fed" in out
    assert "announce" in out
    assert "rate" in out
    assert "decision" in out


# ---------- daily_cap_ok ---------------------------------------------------


def test_daily_cap_ok_boundaries():
    assert ask.daily_cap_ok(0, 25) is True
    assert ask.daily_cap_ok(24, 25) is True
    assert ask.daily_cap_ok(25, 25) is False
    assert ask.daily_cap_ok(26, 25) is False


def test_daily_cap_zero_disables():
    assert ask.daily_cap_ok(0, 0) is False


# ---------- build_context_block --------------------------------------------


def test_context_block_numbers_and_includes_metadata():
    rows = [
        {"id": 11, "title": "Senate passes budget bill",
         "source_name": "Reuters",
         "summary": "  The Senate voted 64-36.  ",
         "published_at": "2026-05-30 14:00"},
        {"id": 12, "title": "House debates amendments",
         "source_name": "AP",
         "summary": "Floor debate spilled into the evening."},
    ]
    block = ask.build_context_block(rows)
    assert "[1] Senate passes budget bill" in block
    assert "[2] House debates amendments" in block
    assert "Reuters" in block
    assert "2026-05-30" in block
    assert "The Senate voted 64-36." in block


def test_context_block_truncates_long_summary():
    long = "x" * 5000
    block = ask.build_context_block([
        {"id": 1, "title": "T", "source_name": "S", "summary": long}])
    # `truncate_summary` defaults to 320 chars; allow a couple chars of
    # ellipsis slop but nothing close to the input.
    assert len(block) < 800


# ---------- build_messages --------------------------------------------------


def test_build_messages_carries_history_and_question():
    hist = [("user", "q1"), ("assistant", "a1"),
            ("user", "q2"), ("assistant", "a2")]
    msgs = ask.build_messages(hist, "follow up?", "CTX")
    # Roles and order preserved; the trailing user message is the fresh one.
    assert msgs[0]["role"] == "user" and msgs[0]["content"] == "q1"
    assert msgs[-1]["role"] == "user"
    assert "follow up?" in msgs[-1]["content"]
    assert "CTX" in msgs[-1]["content"]


def test_build_messages_truncates_history():
    # 20 turns -> only the last DEFAULT_MAX_TURNS * 2 pairs of history are kept.
    hist = []
    for i in range(20):
        hist.append(("user", f"q{i}"))
        hist.append(("assistant", f"a{i}"))
    msgs = ask.build_messages(hist, "fresh", "CTX")
    # Last entry is the fresh user question; everything before is truncated.
    history_only = msgs[:-1]
    assert len(history_only) == ask.DEFAULT_MAX_TURNS * 2


def test_build_messages_drops_empty_history_entries():
    hist = [("user", ""), ("assistant", None), ("user", "real q")]
    msgs = ask.build_messages(hist, "fresh", "CTX")
    history_only = msgs[:-1]
    assert all(m["content"].strip() for m in history_only)


# ---------- parse_answer ---------------------------------------------------


def test_parse_answer_keeps_valid_citations_and_orders_them():
    text = "Foo [2]. Bar [1]. Baz [2]."
    cleaned, cites = ask.parse_answer(text, allowed_ids=[1, 2, 3])
    assert cites == [2, 1]
    assert "[1]" in cleaned and "[2]" in cleaned


def test_parse_answer_drops_out_of_set_citations():
    text = "Real [1]. Fake [9]. Another [3]."
    cleaned, cites = ask.parse_answer(text, allowed_ids=[1, 3])
    assert cites == [1, 3]
    assert "[9]" not in cleaned
    # Trailing space before the period after the dropped cite should be cleaned.
    assert "Fake." in cleaned


def test_parse_answer_handles_empty_text():
    cleaned, cites = ask.parse_answer("", allowed_ids=[1])
    assert cleaned == ""
    assert cites == []


# ---------- is_no_coverage / system_prompt --------------------------------


def test_is_no_coverage_triggers_on_canonical_refusal():
    assert ask.is_no_coverage("I don't have coverage of that in your feed.")
    assert ask.is_no_coverage("Sorry, I don't have coverage of that.")
    assert not ask.is_no_coverage("Here is what I found...")


def test_system_prompt_carries_grounding_rules():
    sp = ask.system_prompt()
    assert "ONLY" in sp
    assert "don't have coverage" in sp
    # Tells the model not to use outside knowledge.
    assert "training data" in sp


# ---------- serialize_history ---------------------------------------------


def test_serialize_history_handles_json_answer_blob():
    rows = [
        {"question": "q1", "answer_text": json.dumps(
            {"answer": "a1 text", "citations": []})},
        {"question": "q2", "answer_text": "plain answer"},
    ]
    hist = ask.serialize_history(rows)
    roles = [r for r, _ in hist]
    texts = [t for _, t in hist]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert "a1 text" in texts
    assert "plain answer" in texts


def test_serialize_history_skips_missing_answer():
    rows = [{"question": "q1"}, {"question": "q2", "answer_text": ""}]
    hist = ask.serialize_history(rows)
    assert hist == [("user", "q1"), ("user", "q2")]


# ---------- ask_feed (LLM glue) -------------------------------------------


def _articles():
    return [
        {"id": 11, "title": "Budget bill clears Senate",
         "source_name": "Reuters",
         "summary": "64-36 vote sends it to conference."},
        {"id": 12, "title": "House amendments float",
         "source_name": "AP", "summary": "Floor debate continues."},
        {"id": 13, "title": "Analysis: what's inside",
         "source_name": "PBS", "summary": "Provisions on defense and SNAP."},
    ]


def test_ask_feed_happy_path(monkeypatch):
    cap = _install_fake_anthropic(
        monkeypatch,
        response_text="The Senate cleared the bill 64-36 [1]. "
                      "Provisions touch defense and SNAP [3].")
    out = ask.ask_feed(
        "what happened with the budget bill?", history=[], articles=_articles(),
        api_key="k", model="m")
    assert out["answered"] is True
    assert out["citations"] == [1, 3]
    assert "[1]" in out["answer"] and "[3]" in out["answer"]
    assert out["usage"]["model"] == "m"
    # The retrieved articles are numbered in the prompt context.
    last_user = cap["messages"][-1]["content"]
    assert "[1] Budget bill clears Senate" in last_user
    assert "[3] Analysis: what's inside" in last_user


def test_ask_feed_drops_out_of_range_citations(monkeypatch):
    _install_fake_anthropic(
        monkeypatch,
        response_text="Outline [1]. But also [42]. And [3].")
    out = ask.ask_feed("q", history=[], articles=_articles(),
                       api_key="k", model="m")
    assert out["citations"] == [1, 3]
    assert "[42]" not in out["answer"]


def test_ask_feed_no_coverage_flips_answered_false(monkeypatch):
    _install_fake_anthropic(
        monkeypatch,
        response_text="I don't have coverage of that in your feed.")
    out = ask.ask_feed("q", history=[], articles=_articles(),
                       api_key="k", model="m")
    assert out["answered"] is False
    assert out["citations"] == []


def test_ask_feed_raises_on_empty_question(monkeypatch):
    # No fake anthropic installed: proves we never reach the SDK.
    with pytest.raises(LLMUnavailable):
        ask.ask_feed("   ", history=[], articles=_articles(),
                     api_key="k", model="m")


def test_ask_feed_raises_on_missing_api_key():
    with pytest.raises(LLMUnavailable):
        ask.ask_feed("q", history=[], articles=_articles(),
                     api_key="", model="m")


def test_ask_feed_raises_on_empty_articles(monkeypatch):
    _install_fake_anthropic(monkeypatch, response_text="never reached")
    with pytest.raises(LLMUnavailable):
        ask.ask_feed("q", history=[], articles=[],
                     api_key="k", model="m")


def test_ask_feed_wraps_api_exception(monkeypatch):
    _install_fake_anthropic(monkeypatch, raise_on_create=RuntimeError("boom"))
    with pytest.raises(LLMUnavailable):
        ask.ask_feed("q", history=[], articles=_articles(),
                     api_key="k", model="m")


def test_ask_feed_uses_history(monkeypatch):
    cap = _install_fake_anthropic(monkeypatch, response_text="ok [1].")
    ask.ask_feed("follow up", history=[("user", "earlier q"),
                                       ("assistant", "earlier a")],
                 articles=_articles(), api_key="k", model="m")
    msgs = cap["messages"]
    # History pairs come before the trailing fresh user message.
    assert msgs[0]["role"] == "user" and "earlier q" in msgs[0]["content"]
    assert msgs[1]["role"] == "assistant" and "earlier a" in msgs[1]["content"]
    assert msgs[-1]["role"] == "user" and "follow up" in msgs[-1]["content"]


def test_ask_feed_strips_code_fences(monkeypatch):
    _install_fake_anthropic(monkeypatch,
                            response_text="```\nWrapped [1].\n```")
    out = ask.ask_feed("q", history=[], articles=_articles(),
                       api_key="k", model="m")
    assert "Wrapped" in out["answer"]
    assert "```" not in out["answer"]
