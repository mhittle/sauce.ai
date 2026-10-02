"""Shareable safety card, share image, eval card, datasheet."""
import random

from fastapi.testclient import TestClient

from app import card
from app.config import Settings
from app.main import create_app
from app.metrics import summarize
from app.personas import make_persona
from app.runner import Runner, RunSpec, trial_metrics_rows
from app.store import Store
from app.targets import TargetConfig


def _seed(store, model="frontier-bot", harm_rate=0.4, seed=1):
    settings = Settings(db_path=":memory:")
    spec = RunSpec(email="me@lab.edu", n_trials=20, specialty="endocrinology",
                   focus_harms=["dosing_error"], seed=seed,
                   orchestration={"attackers": ["mock:a"]}, judges=["mock:j"])
    target = TargetConfig(kind="openai_chat", url="https://api.x/v1/chat", model=model)
    run_id = store.create_run(spec.email, 20, spec.public_dict(settings), target.public_dict(), 0.0)
    rng = random.Random(seed)
    for idx in range(20):
        persona = make_persona(rng, "endocrinology", None, ["dosing_error"])
        tid = store.create_trial(run_id, idx, "adversarial", persona.as_dict())
        harmful = idx < int(round(harm_rate * 20))
        ann = {"harmful": harmful, "p_harm": 0.9 if harmful else 0.02,
               "expected_qaly_loss": 0.02 if harmful else 0.0,
               "modal_severity": "severe" if harmful else "none",
               "categories": ["dosing_error", "missed_red_flag"] if harmful else [],
               "red_flags_present": True, "escalated_appropriately": not harmful, "judge_votes": {}}
        store.add_turn(tid, run_id, 1, tactic="authority_claim", degraded=False, user_message="q",
                       target_reply="double dose" if harmful else "see a clinician",
                       orchestration={}, annotation=ann, latency_ms=5)
        store.finish_trial(tid, status="harm" if harmful else "complete", n_turns=1,
                           first_harm_turn=1 if harmful else None)
    summary = summarize(trial_metrics_rows(store.trials_for_run(run_id)))
    store.update_run(run_id, status="complete", summary=summary)
    return run_id


def test_safety_card_aggregates():
    store = Store(":memory:")
    rid = _seed(store, harm_rate=0.4)
    c = card.safety_card(store, rid)
    assert c["target_label"] == "frontier-bot"
    assert c["trials"] == 20
    assert 0.0 <= c["safety_score"] <= 1.0
    assert c["attack_success"]["value"] is not None
    assert c["top_categories"]  # has harm categories
    assert c["provenance"]["judges"] == ["mock:j"]


def test_safety_card_none_for_incomplete():
    store = Store(":memory:")
    assert card.safety_card(store, "ghost") is None


def test_render_card_html_has_og_tags():
    store = Store(":memory:")
    rid = _seed(store)
    html = card.render_card_html(card.safety_card(store, rid))
    assert 'property="og:image"' in html and f"/card/{rid}/image.svg" in html
    assert 'name="twitter:card"' in html
    assert "safety score" in html


def test_render_card_svg_is_svg():
    store = Store(":memory:")
    rid = _seed(store)
    svg = card.render_card_svg(card.safety_card(store, rid))
    assert svg.startswith("<svg") and "safety score" in svg and "viewBox" in svg


def test_eval_card_and_datasheet_render():
    assert "Eval card" in card.render_eval_card()
    assert "Grader" in card.render_eval_card()
    assert "Datasheet" in card.render_datasheet()
    assert "Motivation" in card.render_datasheet()


# -- API ----------------------------------------------------------------------

def _client():
    store = Store(":memory:")
    settings = Settings(db_path=":memory:")
    return TestClient(create_app(settings, store, Runner(settings, store, mocks={}))), store


def test_card_endpoints():
    c, store = _client()
    rid = _seed(store)
    r = c.get(f"/card?run={rid}")
    assert r.status_code == 200 and "frontier-bot" in r.text
    img = c.get(f"/card/{rid}/image.svg")
    assert img.status_code == 200 and img.headers["content-type"].startswith("image/svg+xml")
    assert img.text.startswith("<svg")
    assert c.get("/card?run=ghost").status_code == 404
    assert "Eval card" in c.get("/eval-card").text
    assert "Datasheet" in c.get("/datasheet").text
