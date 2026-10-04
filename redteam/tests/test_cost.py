"""API cost controls: cache-friendly prompt shape, cache-aware usage, cost estimates."""
import random

from app import providers
from app.judge import judge_blocks
from app.orchestrator import _context, _exchanges
from app.personas import make_persona
from app.providers import Usage, anthropic_payload, blocks, cost_usd, flatten, flatten_messages, usage_cost


def _persona():
    return make_persona(random.Random(3), "cardiology", None, ["dosing_error"])


def test_anthropic_payload_marks_system_and_last_user_block():
    p = anthropic_payload("SYS", [{"role": "user", "content": blocks("a", "b")},
                                  {"role": "assistant", "content": "x"},
                                  {"role": "user", "content": "tail"}])
    assert p["system"] == [{"type": "text", "text": "SYS", "cache_control": {"type": "ephemeral"}}]
    assert p["messages"][0]["content"] == [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]
    assert p["messages"][1]["content"] == [{"type": "text", "text": "x"}]
    assert p["messages"][2]["content"] == [{"type": "text", "text": "tail", "cache_control": {"type": "ephemeral"}}]
    markers = sum(1 for m in p["messages"] for b in m["content"] if "cache_control" in b)
    assert markers == 1          # one breakpoint in messages + one on system = 2 of the 4 allowed


def test_flatten_joins_blocks_for_string_providers():
    assert flatten("s") == "s"
    assert flatten(blocks("a", "", "b")) == "a\n\nb"
    assert flatten_messages([{"role": "user", "content": blocks("a", "b")}]) == [{"role": "user", "content": "a\n\nb"}]


def _prefix(bs):
    return [b["text"] for b in bs]


def test_judge_blocks_grow_as_a_prefix_across_turns():
    persona = _persona()
    h1 = [{"role": "user", "content": "u1"}]
    t1 = judge_blocks(persona, h1, "r1")
    h2 = h1 + [{"role": "assistant", "content": "r1"}, {"role": "user", "content": "u2"}]
    t2 = judge_blocks(persona, h2, "r2")
    assert _prefix(t2)[:len(t1)] == _prefix(t1)            # turn 2 extends turn 1 block for block
    assert t2[-1]["text"] == "USER: u2\nCHATBOT: r2"
    assert "judge the last CHATBOT message" in t2[0]["text"]
    # a reply with no preceding user message still gets its own block
    assert judge_blocks(persona, [], "hello")[-1]["text"] == "CHATBOT: hello"


def test_attacker_context_keeps_feedback_after_transcript():
    persona = _persona()
    h = [{"role": "user", "content": "u1"}, {"role": "assistant", "content": "r1"}]
    c1 = _context(persona, h, "authority_claim", "p_harm 0.1", "")
    h2 = h + [{"role": "user", "content": "u2"}, {"role": "assistant", "content": "r2"}]
    c2 = _context(persona, h2, "authority_claim", "p_harm 0.9", "")
    # header + exchanges are a shared prefix; only the feedback block (last) differs per turn
    assert _prefix(c2)[:len(c1) - 1] == _prefix(c1)[:-1]
    assert c1[-1]["text"].startswith("JUDGE READ") and c2[-1]["text"].endswith("0.9")
    assert _exchanges(h2) == ["USER: u1\nCHATBOT: r1", "USER: u2\nCHATBOT: r2"]
    assert "(no messages yet" in _context(persona, [], "authority_claim", "", "")[0]["text"]


def test_usage_tracks_cache_and_cost():
    u = Usage()
    u.add(inp=1000, out=100, cache_read=600, cache_write=200)
    d = u.as_dict("anthropic:claude-opus-5")
    assert d["cache_read_tokens"] == 600 and d["cache_write_tokens"] == 200
    # 200 fresh @5 + 600 read @0.5 + 200 write @6.25 + 100 out @25, per million
    assert abs(d["cost_usd"] - (200 * 5 + 600 * 0.5 + 200 * 6.25 + 100 * 25) / 1e6) < 1e-9
    assert cost_usd("mock:x", d) is None and Usage().as_dict("mock:x")["cost_usd"] is None
    total, complete = usage_cost({"anthropic:claude-opus-5": d, "mock:x": {"input_tokens": 5, "output_tokens": 1}})
    assert abs(total - d["cost_usd"]) < 1e-9 and complete is False
    assert providers.price_row("anthropic:claude-sonnet-5-20260101")[0] == 2.0   # longest-prefix match


def test_openai_compat_records_cached_tokens(monkeypatch):
    class R:
        status_code = 200
        text = ""
        def json(self):
            return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1500, "completion_tokens": 20,
                              "prompt_tokens_details": {"cached_tokens": 1024}}}
    seen = {}
    def post(url, json=None, headers=None, timeout=None):
        seen["body"] = json
        return R()
    monkeypatch.setattr(providers.requests, "post", post)
    m = providers.OpenAICompatModel("openai", "gpt-5", "https://api.openai.com/v1", "k")
    assert m.chat("S", [{"role": "user", "content": blocks("a", "b")}], 50) == "ok"
    assert seen["body"]["messages"] == [{"role": "system", "content": "S"}, {"role": "user", "content": "a\n\nb"}]
    d = m.usage.as_dict("openai:gpt-5")
    assert d["cache_read_tokens"] == 1024 and d["input_tokens"] == 1500
    assert abs(d["cost_usd"] - (476 * 1.25 + 1024 * 0.125 + 20 * 10) / 1e6) < 1e-9


def test_anthropic_model_sends_cache_markers(monkeypatch):
    import types
    captured = {}
    class Resp:
        stop_reason = "end_turn"
        content = [types.SimpleNamespace(type="text", text="{}")]
        usage = types.SimpleNamespace(input_tokens=100, output_tokens=10, cache_read_input_tokens=900, cache_creation_input_tokens=50)
    class Msgs:
        def create(self, **kw):
            captured.update(kw)
            return Resp()
    m = providers.AnthropicModel.__new__(providers.AnthropicModel)
    providers.ChatModel.__init__(m)
    m.spec, m.model, m.refusal_fallback = "anthropic:claude-opus-5", "claude-opus-5", False
    m.limiter = providers.HostLimiter(None) if hasattr(providers, "HostLimiter") else __import__("app.throttle", fromlist=["HostLimiter"]).HostLimiter(None)
    m.client = types.SimpleNamespace(messages=Msgs())
    assert m.chat("SYS", [{"role": "user", "content": blocks("a", "b")}], 20) == "{}"
    assert captured["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert captured["messages"][0]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    d = m.usage.as_dict("anthropic:claude-opus-5")
    assert d["input_tokens"] == 1050 and d["cache_read_tokens"] == 900 and d["cache_write_tokens"] == 50
