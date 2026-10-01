"""Ablation & baseline harness: arm matrix, matched expansion, contrasts, API."""
import random

from fastapi.testclient import TestClient

from app import ablation
from app.config import Settings
from app.main import create_app
from app.metrics import summarize
from app.personas import make_persona
from app.runner import Runner, RunSpec, trial_metrics_rows
from app.store import Store
from app.targets import TargetConfig

BASE = {
    "email": "me@lab.edu", "n_trials": 10, "specialty": "endocrinology",
    "focus_harms": ["dosing_error"], "max_turns": 8, "stop_on_harm": True,
    "orchestration": {"attackers": ["p:a", "p:b"], "levels": 2, "consensus_rounds": 1,
                      "lookahead": True, "bandit": True},
}


# -- arm matrix ---------------------------------------------------------------

def test_apply_arm_toggles_one_component():
    full = ablation.apply_arm(BASE, ablation.ARMS_BY_KEY["full"])
    assert full["orchestration"]["bandit"] is True
    assert full["orchestration"]["attackers"] == ["p:a", "p:b"]

    nb = ablation.apply_arm(BASE, ablation.ARMS_BY_KEY["no_bandit"])
    assert nb["orchestration"]["bandit"] is False
    assert nb["orchestration"]["levels"] == 2  # nothing else changed

    sa = ablation.apply_arm(BASE, ablation.ARMS_BY_KEY["single_attacker"])
    assert sa["orchestration"]["attackers"] == ["p:a"]

    sp = ablation.apply_arm(BASE, ablation.ARMS_BY_KEY["single_prompt"])
    assert sp["max_turns"] == 1 and sp["orchestration"]["attackers"] == ["p:a"]
    assert sp["orchestration"]["bandit"] is False and sp["orchestration"]["levels"] == 1


def test_apply_arm_does_not_mutate_base():
    ablation.apply_arm(BASE, ablation.ARMS_BY_KEY["single_attacker"])
    assert BASE["orchestration"]["attackers"] == ["p:a", "p:b"]


def test_expand_tags_every_arm():
    specs = ablation.expand(BASE, "abl1")
    assert len(specs) == len(ablation.ARMS)
    assert {s["ablation_arm"] for s in specs} == set(ablation.arm_keys())
    assert all(s["ablation_id"] == "abl1" for s in specs)

    subset = ablation.expand(BASE, "abl2", ["full", "no_bandit"])
    assert [s["ablation_arm"] for s in subset] == ["full", "no_bandit"]


# -- analysis -----------------------------------------------------------------

def _seed_arm(store, arm, harm_rate, ablation_id, seed=1):
    """A completed run tagged with (ablation_id, arm) at ~harm_rate."""
    settings = Settings(db_path=":memory:")
    spec = RunSpec(email="me@lab.edu", n_trials=20, specialty="endocrinology",
                   focus_harms=["dosing_error"], seed=seed,
                   orchestration={"attackers": ["mock:a"]}, judges=["mock:j"],
                   ablation_id=ablation_id, ablation_arm=arm)
    target = TargetConfig(kind="openai_chat", url="https://api.x/v1/chat", model="bot-x")
    run_id = store.create_run(spec.email, 20, spec.public_dict(settings), target.public_dict(), 0.0)
    rng = random.Random(seed)
    for idx in range(20):
        persona = make_persona(rng, "endocrinology", None, ["dosing_error"])
        tid = store.create_trial(run_id, idx, "adversarial", persona.as_dict())
        harmful = idx < int(round(harm_rate * 20))
        ann = {"harmful": harmful, "p_harm": 0.9 if harmful else 0.02,
               "expected_qaly_loss": 0.02 if harmful else 0.0,
               "modal_severity": "severe" if harmful else "none",
               "categories": ["dosing_error"] if harmful else [], "red_flags_present": True,
               "escalated_appropriately": not harmful, "judge_votes": {}}
        store.add_turn(tid, run_id, 1, tactic="authority_claim", degraded=False, user_message="q",
                       target_reply="double dose" if harmful else "see a clinician",
                       orchestration={}, annotation=ann, latency_ms=5)
        store.finish_trial(tid, status="harm" if harmful else "complete", n_turns=1,
                           first_harm_turn=1 if harmful else None)
    summary = summarize(trial_metrics_rows(store.trials_for_run(run_id)))
    store.update_run(run_id, status="complete", summary=summary)
    return run_id


def test_store_finds_runs_for_ablation():
    store = Store(":memory:")
    _seed_arm(store, "full", 0.6, "ablA", seed=1)
    _seed_arm(store, "no_bandit", 0.3, "ablA", seed=2)
    _seed_arm(store, "full", 0.5, "ablB", seed=3)  # different set
    assert len(store.runs_for_ablation("ablA")) == 2
    assert len(store.runs_for_ablation("ablB")) == 1


def test_analyze_contrasts_against_reference():
    store = Store(":memory:")
    _seed_arm(store, "full", 0.70, "ablA", seed=1)
    _seed_arm(store, "no_bandit", 0.30, "ablA", seed=2)
    _seed_arm(store, "single_prompt", 0.10, "ablA", seed=3)
    an = ablation.analyze(store, store.runs_for_ablation("ablA"))
    assert an["has_reference"] and an["n_arms"] == 3
    rows = {a["key"]: a for a in an["arms"]}
    # reference has no delta
    assert rows["full"]["delta_vs_full"] is None
    # removing the bandit drops attack success -> positive component contribution
    assert rows["no_bandit"]["delta_vs_full"]["value"] > 0
    assert rows["single_prompt"]["delta_vs_full"]["value"] > 0
    # the full stack beats the single-prompt baseline by more than the bandit alone
    assert rows["single_prompt"]["delta_vs_full"]["value"] > rows["no_bandit"]["delta_vs_full"]["value"]
    assert rows["no_bandit"]["logrank"] is not None


def test_analyze_without_reference_blanks_deltas():
    store = Store(":memory:")
    _seed_arm(store, "no_bandit", 0.3, "ablN", seed=1)
    an = ablation.analyze(store, store.runs_for_ablation("ablN"))
    assert an["has_reference"] is False
    assert an["arms"][0]["delta_vs_full"] is None


# -- API ----------------------------------------------------------------------

def _client():
    store = Store(":memory:")
    settings = Settings(db_path=":memory:")
    return TestClient(create_app(settings, store, Runner(settings, store, mocks={}))), store


def test_ablation_report_api():
    c, store = _client()
    _seed_arm(store, "full", 0.6, "ablA", seed=1)
    _seed_arm(store, "no_bandit", 0.2, "ablA", seed=2)
    j = c.get("/ablation/ablA.json").json()
    assert j["n_arms"] == 2 and j["target_label"] == "bot-x"
    html = c.get("/ablation/ablA").text
    assert "Ablation" in html and "Random tactic" in html and "vs full" in html
    assert c.get("/ablation/ghost").status_code == 404


def test_ablation_launch_rejects_unknown_arm():
    c, _ = _client()
    body = {"email": "me@lab.edu", "n_trials": 2, "specialty": "endocrinology",
            "arms": ["full", "bogus"],
            "target": {"kind": "openai_chat", "url": "https://api.x/v1/chat", "model": "m"}}
    r = c.post("/ablation", json=body)
    assert r.status_code == 400 and "bogus" in r.json()["detail"]
