"""Unit tests for the natural-language algorithm interpreter.

`anthropic` is stubbed via `sys.modules` (same pattern as
`test_framing.py`) so these run without the SDK installed; the
production helper imports it lazily.
"""
import json
import sys
import types

import pytest

from app.classifier import LLMUnavailable
from app import algo_nl
from app.ranking import build_score_sql, weights_to_expression, FEATURE_KEYS


def _install_fake_anthropic(monkeypatch, *, response_text=None, raise_on_create=None):
    class _Block:
        def __init__(self, t, text):
            self.type = t
            self.text = text

    class _Usage:
        input_tokens = 120
        output_tokens = 60
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


def _resp(weights=None, recency=0.7, category_filter=None, notes="did the thing"):
    return json.dumps({
        "weights": weights or {},
        "recency": recency,
        "category_filter": category_filter or [],
        "notes": notes,
    })


def test_happy_path_shape_and_usage(monkeypatch):
    captured = _install_fake_anthropic(monkeypatch, response_text=_resp(
        weights={"objectivity": {"weight": 1.5, "direction": 1.0, "threshold": None},
                 "paywall": {"weight": 0.8, "direction": 0.0, "threshold": 0.2}},
        recency=0.9, category_filter=["tech", "science"], notes="High objectivity, free, fresh.",
    ))
    out = algo_nl.interpret_algorithm("just the facts, no paywalls",
                                      api_key="k", model="m")
    w = out["weights"]
    assert w["objectivity"] == 1.5
    assert w["objectivity_direction"] == 1.0
    assert w["objectivity_threshold"] is None
    assert w["paywall"] == 0.8
    assert w["paywall_threshold"] == 0.2
    assert w["recency"] == 0.9
    assert w["category_filter"] == ["tech", "science"]
    assert out["notes"] == "High objectivity, free, fresh."
    assert out["usage"]["model"] == "m"
    # The description is forwarded to the model.
    assert "just the facts" in captured["messages"][0]["content"]


def test_system_prompt_carries_live_catalog(monkeypatch):
    captured = _install_fake_anthropic(monkeypatch, response_text=_resp(
        weights={"objectivity": {"weight": 1.0, "direction": 1.0}}))
    algo_nl.interpret_algorithm("x", api_key="k", model="m")
    sys_text = captured["system"][0]["text"]
    # Catalog is generated from ranking.FEATURES, not hard-coded.
    assert "political_lean" in sys_text
    assert "source_obscurity" in sys_text
    assert "Objectivity" in sys_text


def test_clamps_out_of_range_weight_direction_recency(monkeypatch):
    _install_fake_anthropic(monkeypatch, response_text=_resp(
        weights={
            "objectivity": {"weight": 9.0, "direction": 5.0},        # unsigned
            "political_lean": {"weight": -3.0, "direction": -7.0},   # signed
        },
        recency=99,
    ))
    w = algo_nl.interpret_algorithm("loud", api_key="k", model="m")["weights"]
    assert w["objectivity"] == 2.0           # weight clamped to [0, 2]
    assert w["objectivity_direction"] == 1.0  # unsigned direction clamped to [0, 1]
    assert w["political_lean"] == 0.0         # negative weight clamped to 0
    assert w["political_lean_direction"] == -1.0  # signed clamped to [-1, 1]
    assert w["recency"] == 2.0


def test_threshold_normalization(monkeypatch):
    _install_fake_anthropic(monkeypatch, response_text=_resp(weights={
        "objectivity": {"weight": 1.0, "direction": 1.0, "threshold": -1},   # neg -> off
        "info_density": {"weight": 1.0, "direction": 1.0, "threshold": 9},   # clamp to 1.0
        "political_lean": {"weight": 0.5, "direction": 0.0, "threshold": 9}, # clamp to 2.0 (signed)
        "popularity": {"weight": 0.5, "direction": 0.5, "threshold": "bad"}, # junk -> off
    }))
    w = algo_nl.interpret_algorithm("x", api_key="k", model="m")["weights"]
    assert w["objectivity_threshold"] is None
    assert w["info_density_threshold"] == 1.0
    assert w["political_lean_threshold"] == 2.0
    assert w["popularity_threshold"] is None


def test_drops_unknown_feature_and_category(monkeypatch):
    _install_fake_anthropic(monkeypatch, response_text=_resp(
        weights={"made_up_feature": {"weight": 2.0, "direction": 1.0},
                 "objectivity": {"weight": 1.0, "direction": 1.0}},
        category_filter=["tech", "not-a-cat"],
    ))
    w = algo_nl.interpret_algorithm("x", api_key="k", model="m")["weights"]
    assert "made_up_feature" not in w
    assert "objectivity" in w
    assert w["category_filter"] == ["tech"]


def test_strips_code_fences(monkeypatch):
    _install_fake_anthropic(
        monkeypatch,
        response_text='```json\n' + _resp(
            weights={"objectivity": {"weight": 1.0, "direction": 1.0}}) + '\n```',
    )
    out = algo_nl.interpret_algorithm("x", api_key="k", model="m")
    assert out["weights"]["objectivity"] == 1.0


def test_empty_description_raises_before_api(monkeypatch):
    # No fake anthropic installed: proves we never reach the SDK.
    with pytest.raises(LLMUnavailable):
        algo_nl.interpret_algorithm("   ", api_key="k", model="m")


def test_no_api_key_raises():
    with pytest.raises(LLMUnavailable):
        algo_nl.interpret_algorithm("real description", api_key="", model="m")


def test_api_exception_wrapped(monkeypatch):
    _install_fake_anthropic(monkeypatch, raise_on_create=RuntimeError("boom"))
    with pytest.raises(LLMUnavailable):
        algo_nl.interpret_algorithm("desc", api_key="k", model="m")


def test_unparseable_json_raises(monkeypatch):
    _install_fake_anthropic(monkeypatch, response_text="totally not json")
    with pytest.raises(LLMUnavailable):
        algo_nl.interpret_algorithm("desc", api_key="k", model="m")


def test_non_object_json_raises(monkeypatch):
    _install_fake_anthropic(monkeypatch, response_text="[1, 2, 3]")
    with pytest.raises(LLMUnavailable):
        algo_nl.interpret_algorithm("desc", api_key="k", model="m")


def test_all_zero_weights_raises(monkeypatch):
    _install_fake_anthropic(monkeypatch, response_text=_resp(
        weights={"objectivity": {"weight": 0, "direction": 1.0}}, recency=0))
    with pytest.raises(LLMUnavailable):
        algo_nl.interpret_algorithm("desc", api_key="k", model="m")


def test_recency_only_is_usable(monkeypatch):
    _install_fake_anthropic(monkeypatch, response_text=_resp(weights={}, recency=1.0))
    out = algo_nl.interpret_algorithm("just the freshest news",
                                      api_key="k", model="m")
    assert out["weights"]["recency"] == 1.0


def test_output_feeds_ranking_helpers(monkeypatch):
    _install_fake_anthropic(monkeypatch, response_text=_resp(weights={
        "objectivity": {"weight": 1.2, "direction": 1.0, "threshold": 0.3},
        "political_lean": {"weight": 0.5, "direction": 0.0},
    }, recency=0.8))
    w = algo_nl.interpret_algorithm("balanced and objective",
                                    api_key="k", model="m")["weights"]
    expr, params = build_score_sql(w)
    assert isinstance(expr, str) and isinstance(params, dict)
    assert "objectivity_w" in params
    code = weights_to_expression(w)
    assert "def score(article):" in code
    # Every emitted key is canonical (a feature key, its _direction /
    # _threshold, recency, or category_filter) — nothing leaks through.
    valid = set()
    for fk in FEATURE_KEYS:
        valid.update({fk, f"{fk}_direction", f"{fk}_threshold"})
    valid.update({"recency", "category_filter"})
    assert set(w).issubset(valid)
