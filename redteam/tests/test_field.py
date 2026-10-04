"""Field scan: panel, availability, comparative results, harm image, endpoints."""
import random
import xml.dom.minidom as minidom

from fastapi.testclient import TestClient

from app import field
from app.config import Settings
from app.main import create_app
from app.metrics import summarize
from app.personas import make_persona
from app.runner import Runner, RunQueue, RunSpec, trial_metrics_rows
from app.store import Store
from app.targets import TargetConfig


# -- panel --------------------------------------------------------------------

def test_panel_has_the_main_agents():
    models = {p["display"] for p in field.FIELD_PANEL}
    assert any("ChatGPT" in m for m in models)
    assert any("Claude" in m for m in models)
    assert any("Gemini" in m for m in models)
    assert any("Llama" in m for m in models)


def test_available_panel_tracks_keys():
    none = Settings(db_path=":memory:", anthropic_api_key=None, openai_api_key=None,
                    gemini_api_key=None, llama_api_key=None, llama_base_url="https://api.together.xyz/v1")
    runnable, skipped = field.available_panel(none)
    assert runnable == [] and len(skipped) == len(field.FIELD_PANEL)

    have = Settings(db_path=":memory:", anthropic_api_key="x", openai_api_key="y",
                    gemini_api_key=None, llama_api_key=None, llama_base_url="https://api.together.xyz/v1")
    runnable, skipped = field.available_panel(have)
    provs = {p["provider"] for p in runnable}
    assert provs == {"anthropic", "openai"}
    assert all(s["provider"] in ("gemini", "llama") for s in skipped)


def test_target_for_builds_provider_targets():
    s = Settings(db_path=":memory:", anthropic_api_key="ak", openai_api_key="ok")
    anth = field.target_for(field.PANEL_BY_KEY["claude-opus-5"], s)
    assert anth["kind"] == "anthropic" and anth["api_key"] == "ak" and anth["system_prompt"]
    gpt = field.target_for(field.PANEL_BY_KEY["chatgpt-5"], s)
    assert gpt["kind"] == "openai_chat" and gpt["model"] == "gpt-5" and gpt["url"]


# -- results + image ----------------------------------------------------------

def _seed(store, model, harm_rate, field_id="F1", seed=1, condition="type 2 diabetes"):
    settings = Settings(db_path=":memory:")
    spec = RunSpec(email="me@lab.edu", n_trials=20, specialty="endocrinology", condition=condition,
                   focus_harms=["dosing_error"], seed=seed, orchestration={"attackers": ["mock:a"]},
                   judges=["mock:j"], field_scan_id=field_id)
    target = TargetConfig(kind="openai_chat", url="https://api.x/v1/chat", model=model)
    run_id = store.create_run(spec.email, 20, spec.public_dict(settings), target.public_dict(), 0.0)
    rng = random.Random(seed)
    for idx in range(20):
        persona = make_persona(rng, "endocrinology", "type 2 diabetes", ["dosing_error"])
        tid = store.create_trial(run_id, idx, "adversarial", persona.as_dict())
        harmful = idx < int(round(harm_rate * 20))
        ann = {"harmful": harmful, "p_harm": 0.9 if harmful else 0.02,
               "expected_qaly_loss": 0.02 if harmful else 0.0,
               "modal_severity": "death" if harmful else "none",
               "categories": ["dosing_error"] if harmful else [], "red_flags_present": True,
               "escalated_appropriately": not harmful, "judge_votes": {}}
        store.add_turn(tid, run_id, 1, tactic="authority_claim", degraded=False, user_message="q",
                       target_reply="double dose" if harmful else "see a clinician",
                       orchestration={}, annotation=ann, latency_ms=5)
        store.finish_trial(tid, status="harm" if harmful else "complete", n_turns=1,
                           first_harm_turn=1 if harmful else None)
    store.update_run(run_id, status="complete",
                     summary=summarize(trial_metrics_rows(store.trials_for_run(run_id))))
    return run_id


def test_field_results_ranks_safest_first_and_maps_display():
    store = Store(":memory:")
    _seed(store, "gpt-5", 0.6)
    _seed(store, "claude-opus-5", 0.15, seed=2)
    _seed(store, "gemini-2.5-pro", 0.35, seed=3)
    res = field.field_results(store, store.runs_for_field("F1"))
    assert res["n_models"] == 3 and res["condition"] == "type 2 diabetes"
    order = [e["display"] for e in res["entries"]]
    assert order[0] == "Claude (Opus 5)"   # safest first
    assert order[-1] == "ChatGPT (GPT-5)"  # most harmful last
    assert res["entries"][0]["rank"] == 1
    assert res["entries"][-1]["critical_count"] > 0


def test_harm_chart_and_share_svg_well_formed():
    store = Store(":memory:")
    _seed(store, "gpt-5", 0.6)
    _seed(store, "claude-opus-5", 0.15, seed=2)
    res = field.field_results(store, store.runs_for_field("F1"))
    for svg in (field.harm_chart_svg(res), field.share_svg(res)):
        minidom.parseString(svg)
        assert svg.startswith("<svg")
        assert "Claude (Opus 5)" in svg
    assert "type 2 diabetes" in field.harm_chart_svg(res)


# -- API ----------------------------------------------------------------------

def test_field_ad_hoc_endpoints():
    store = Store(":memory:")
    settings = Settings(db_path=":memory:")
    app = create_app(settings, store, Runner(settings, store, mocks={}))
    _seed(store, "gpt-5", 0.6)
    _seed(store, "claude-opus-5", 0.15, seed=2)
    c = TestClient(app)
    j = c.get("/field.json?field=F1").json()
    assert j["n_models"] == 2 and j["entries"][0]["display"] == "Claude (Opus 5)"
    html = c.get("/field?field=F1").text
    assert "field scan" in html and "Claude (Opus 5)" in html
    img = c.get("/field.svg?field=F1")
    assert img.headers["content-type"].startswith("image/svg+xml")
    share = c.get("/field.svg?field=F1&share=1").text
    assert "Who gives the safest health advice" in share
    assert c.get("/field.json").status_code == 400  # no field/runs


def test_field_launch_requires_keys_and_validates_models(monkeypatch):
    store = Store(":memory:")
    # no provider keys -> nothing runnable
    settings = Settings(db_path=":memory:", anthropic_api_key=None, openai_api_key=None,
                        gemini_api_key=None, llama_api_key=None, llama_base_url="https://api.together.xyz/v1")
    app = create_app(settings, store, Runner(settings, store, mocks={}))
    c = TestClient(app)
    r = c.post("/field", json={"email": "me@lab.edu", "specialty": "endocrinology", "n_trials": 2})
    assert r.status_code == 400 and "no panel providers" in r.json()["detail"]
    r2 = c.post("/field", json={"email": "me@lab.edu", "specialty": "endocrinology",
                                "models": ["bogus"], "n_trials": 2})
    assert r2.status_code == 400 and "bogus" in r2.json()["detail"]


def test_field_launch_creates_runs(monkeypatch):
    # with an OpenAI key, a field scan restricted to ChatGPT plans one run (no execution)
    monkeypatch.setattr(RunQueue, "submit", lambda self, *a, **k: None)
    store = Store(":memory:")
    settings = Settings(db_path=":memory:", openai_api_key="ok", anthropic_api_key=None,
                        gemini_api_key=None, llama_api_key=None, llama_base_url="https://api.together.xyz/v1")
    app = create_app(settings, store, Runner(settings, store, mocks={}))
    c = TestClient(app)
    r = c.post("/field", json={"email": "me@lab.edu", "specialty": "endocrinology",
                               "condition": "type 2 diabetes", "n_trials": 3, "models": ["chatgpt-5"]})
    assert r.status_code == 200
    body = r.json()
    assert body["n_models"] == 1 and body["runs"][0]["display"] == "ChatGPT (GPT-5)"
    assert len(store.runs_for_field(body["field_id"])) == 1


def test_target_for_posts_to_the_chat_completions_endpoint():
    s = Settings(db_path=":memory:", openai_api_key="ok", gemini_api_key="gk",
                 gemini_base_url="https://generativelanguage.googleapis.com/v1beta/models/",
                 llama_api_key=None, openrouter_api_key="ork", llama_base_url="https://api.together.xyz/v1")
    gpt = field.target_for(field.PANEL_BY_KEY["chatgpt-5"], s)
    assert gpt["url"] == "https://api.openai.com/v1/chat/completions"
    # a pasted native Gemini URL is mapped to the OpenAI-compatible endpoint
    gem = field.target_for(field.PANEL_BY_KEY["gemini-pro"], s)
    assert gem["url"] == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert gem["api_key"] == "gk" and gem["model"] == "gemini-2.5-pro"
    # no LLAMA key but an OpenRouter key: the llama panel entry goes through OpenRouter with its id
    ll = field.target_for(field.PANEL_BY_KEY["llama-70b"], s)
    assert ll["url"] == "https://openrouter.ai/api/v1/chat/completions" and ll["api_key"] == "ork"
    assert ll["model"] == "meta-llama/llama-3.3-70b-instruct"
    assert field._MODEL_DISPLAY[ll["model"]] == "Llama 3.3 70B (Meta)"
    assert {p["provider"] for p in field.available_panel(s)[0]} == {"openai", "gemini", "llama"}
