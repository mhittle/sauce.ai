"""Public safety leaderboard: scoring, auto-record, ranking, overall pooling, API."""
import random

from fastapi.testclient import TestClient

from app import leaderboard
from app.config import Settings
from app.main import create_app
from app.metrics import summarize
from app.personas import make_persona
from app.runner import Runner, trial_metrics_rows
from app.store import Store
from app.targets import TargetConfig


def _adv(severity_counts, responses, conv_risk=0.4):
    return {"trials": 20, "responses": responses, "severity_counts": severity_counts,
            "conversation_risk": {"value": conv_risk, "lo": 0.2, "hi": 0.6},
            "response_risk": {"value": conv_risk, "lo": 0.2, "hi": 0.6},
            "nnh_conversations": {"value": 2.5},
            "prompts_until_harm": {"km": {"median": 2}},
            "expected_qalys_lost_per_1000_conversations": {"mean": 12.0},
            "escalation_sensitivity": {"value": 0.6}}


# -- scoring ------------------------------------------------------------------

def test_safety_score_bounds_and_direction():
    assert leaderboard.safety_score({"responses": 0, "severity_counts": {}}) is None
    perfect = leaderboard.safety_score({"responses": 10, "severity_counts": {}})
    assert perfect == 1.0
    worst = leaderboard.safety_score({"responses": 10, "severity_counts": {"death": 10}})
    assert worst == 0.0
    mid = leaderboard.safety_score({"responses": 10, "severity_counts": {"moderate": 5}})
    assert 0.0 < mid < 1.0
    # more severe harm scores strictly lower
    a = leaderboard.safety_score({"responses": 10, "severity_counts": {"mild": 4}})
    b = leaderboard.safety_score({"responses": 10, "severity_counts": {"death": 4}})
    assert a > b


def test_critical_count_counts_severe_and_death_only():
    assert leaderboard.critical_count({"severity_counts": {"mild": 3, "moderate": 2}}) == 0
    assert leaderboard.critical_count({"severity_counts": {"severe": 2, "death": 1, "mild": 9}}) == 3


def test_entry_from_run_none_when_no_adversarial():
    run = {"id": "r", "config": {"specialty": "cardiology"}}
    assert leaderboard.entry_from_run(run, {"adversarial": {"trials": 0}}) is None


def test_entry_from_run_shape():
    run = {"id": "r1", "created_at": 1.0,
           "config": {"specialty": "cardiology", "harm_threshold": 0.1,
                      "orchestration": {"attackers": ["a", "b"]}, "judges": ["j"]},
           "target": {"kind": "openai_chat", "model": "gpt-x"}}
    e = leaderboard.entry_from_run(run, {"adversarial": _adv({"severe": 2}, 20)})
    assert e["target_label"] == "gpt-x"
    assert e["specialty"] == "cardiology"
    assert e["critical_count"] == 2
    assert 0.0 <= e["safety_score"] <= 1.0
    assert e["n_attackers"] == 2 and e["n_judges"] == 1


# -- store upsert / read ------------------------------------------------------

def _seed(store, model, harm_rate, specialty="endocrinology", seed=1):
    """Create a completed run with 20 single-turn trials at ~harm_rate, set its
    summary, and fold it into the leaderboard exactly as the runner does."""
    settings = Settings(db_path=":memory:")
    from app.runner import RunSpec
    spec = RunSpec(email="me@lab.edu", n_trials=20, specialty=specialty,
                   focus_harms=["dosing_error"], seed=seed,
                   orchestration={"attackers": ["mock:a"]}, judges=["mock:j"])
    target = TargetConfig(kind="openai_chat", url="https://api.x/v1/chat", model=model)
    run_id = store.create_run(spec.email, 20, spec.public_dict(settings), target.public_dict(), 0.0)
    rng = random.Random(seed)
    for idx in range(20):
        persona = make_persona(rng, specialty, None, ["dosing_error"])
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
    summary = summarize(trial_metrics_rows(store.trials_for_run(run_id)))
    store.update_run(run_id, status="complete", summary=summary)
    leaderboard.record_run(store, run_id)
    return run_id


def test_upsert_is_idempotent_per_run():
    store = Store(":memory:")
    rid = _seed(store, "gpt-x", 0.3)
    leaderboard.record_run(store, rid)  # re-record same run
    leaderboard.record_run(store, rid)
    entries = store.leaderboard_entries()
    assert len(entries) == 1
    assert entries[0]["n_runs"] == 1  # same run_id never double-counts


def test_new_run_for_same_pair_increments_and_replaces():
    store = Store(":memory:")
    _seed(store, "gpt-x", 0.5, seed=1)
    _seed(store, "gpt-x", 0.1, seed=2)  # a fresh, safer run for the same target+specialty
    entries = store.leaderboard_entries()
    assert len(entries) == 1
    assert entries[0]["n_runs"] == 2  # two distinct runs pooled into the pair


def test_board_ranks_safest_first():
    store = Store(":memory:")
    _seed(store, "safe-bot", 0.1)
    _seed(store, "leaky-bot", 0.7, seed=2)
    _seed(store, "mid-bot", 0.4, seed=3)
    bd = leaderboard.board(store, "endocrinology")
    labels = [e["target_label"] for e in bd["entries"]]
    assert labels == ["safe-bot", "mid-bot", "leaky-bot"]  # safest first
    assert bd["entries"][0]["rank"] == 1
    assert bd["categories"] == ["endocrinology"]


def test_overall_pools_across_specialties():
    store = Store(":memory:")
    _seed(store, "gpt-x", 0.2, specialty="endocrinology", seed=1)
    _seed(store, "gpt-x", 0.6, specialty="cardiology", seed=2)
    bd = leaderboard.board(store)  # overall
    assert bd["category"] == "overall"
    assert bd["n_targets"] == 1
    row = bd["entries"][0]
    assert row["trials"] == 40  # 20 + 20 pooled
    assert row["n_specialties"] == 2


# -- API ----------------------------------------------------------------------

def test_leaderboard_api():
    store = Store(":memory:")
    settings = Settings(db_path=":memory:")
    app = create_app(settings, store, Runner(settings, store, mocks={}))
    _seed(store, "safe-bot", 0.1)
    _seed(store, "leaky-bot", 0.7, seed=2)
    c = TestClient(app)

    j = c.get("/leaderboard.json?category=endocrinology").json()
    assert j["category"] == "endocrinology"
    assert [e["target_label"] for e in j["entries"]] == ["safe-bot", "leaky-bot"]

    overall = c.get("/leaderboard.json").json()
    assert overall["category"] == "overall"

    html = c.get("/leaderboard").text
    assert "Clinical AI safety leaderboard" in html
    assert "safe-bot" in html and "leaky-bot" in html
    assert "Safety" in html


def test_empty_leaderboard_renders():
    store = Store(":memory:")
    settings = Settings(db_path=":memory:")
    app = create_app(settings, store, Runner(settings, store, mocks={}))
    html = TestClient(app).get("/leaderboard").text
    assert "No runs on this leaderboard yet" in html
