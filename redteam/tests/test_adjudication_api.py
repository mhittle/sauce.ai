"""End-to-end adjudication: seed a run's turns, build a set, submit labels
from two raters, and check the analysis (agreement + judge-vs-human)."""
import random

import pytest
from fastapi.testclient import TestClient

from app import adjudication as adj
from app.config import Settings
from app.main import create_app
from app.personas import make_persona
from app.runner import Runner, RunSpec
from app.store import Store
from app.targets import TargetConfig


def _seed_run(store, n_trials=8):
    settings = Settings(db_path=":memory:")
    spec = RunSpec(email="me@lab.edu", n_trials=n_trials, specialty="endocrinology",
                   focus_harms=["dosing_error"],
                   orchestration={"attackers": ["mock:a"], "arbiters": ["mock:b"]}, judges=["mock:j"])
    run_id = store.create_run(spec.email, n_trials, spec.public_dict(settings),
                              TargetConfig(kind="openai_chat", url="https://x").public_dict(), 0.0)
    rng = random.Random(3)
    for idx in range(n_trials):
        persona = make_persona(rng, "endocrinology", None, ["dosing_error"])
        tid = store.create_trial(run_id, idx, "adversarial", persona.as_dict())
        harmful = idx % 2 == 0
        p = 0.85 if harmful else 0.04
        ann = {"harmful": harmful, "p_harm": p, "expected_qaly_loss": 0.02 if harmful else 0.0,
               "modal_severity": "severe" if harmful else "none",
               "categories": ["dosing_error"] if harmful else [], "red_flags_present": True,
               "escalated_appropriately": not harmful, "judge_votes": {}, "correct_guidance": "x",
               "rationale": "y", "evidence_quotes": []}
        store.add_turn(tid, run_id, 1, tactic="authority_claim", degraded=False,
                       user_message="q", target_reply="take a double dose" if harmful else "see a clinician",
                       orchestration={}, annotation=ann, latency_ms=5)
        store.finish_trial(tid, status="harm" if harmful else "complete", n_turns=1,
                           first_harm_turn=1 if harmful else None)
    return run_id


def test_analyze_set_agreement_and_diagnostic():
    store = Store(":memory:")
    run_id = _seed_run(store, 12)
    turns = adj.turns_from_trials(run_id, store.trials_for_run(run_id))
    sampled = adj.stratified_sample(turns, adj.SampleSpec(n=12, seed=1, allocation="uniform"))
    judged = {u["id"]: (u["p_harm"], bool(u["harmful"]))
              for t in store.trials_for_run(run_id) for u in t["turns"]}
    items = [{"turn_id": s.turn_id, "run_id": s.run_id, "stratum": s.stratum, "harm_bin": s.harm_bin,
              "inclusion_prob": s.inclusion_prob, "judge_p_harm": judged[s.turn_id][0],
              "judge_harmful": judged[s.turn_id][1], "context": s.context} for s in sampled]
    set_id = store.create_adjudication_set("t", {}, [run_id], items)

    stored = store.adjudication_items(set_id, blinded=False)
    # rater A agrees with the judge; rater B agrees too but flips one item -> imperfect agreement
    for n, it in enumerate(stored):
        jh = bool(it["judge_harmful"])
        store.submit_label(set_id, it["id"], "A", harmful=jh, severity=3 if jh else None,
                           categories=["dosing_error"] if jh else [], escalated=not jh,
                           confidence=3, notes=None)
        b = (not jh) if n == 0 else jh
        store.submit_label(set_id, it["id"], "B", harmful=b, severity=3 if b else None,
                           categories=["dosing_error"] if b else [], escalated=not b,
                           confidence=2, notes=None)

    res = adj.analyze_set(store.adjudication_items(set_id, blinded=False),
                          store.adjudication_labels(set_id))
    inter = res["inter_rater"]
    assert inter["method"] == "two-rater" and inter["n_raters"] == 2
    assert 0.5 < inter["cohen_kappa"] < 1.0 and inter["gwet_ac1"] is not None
    jvh = res["judge_vs_human"]
    assert jvh["n_evaluable"] >= 10
    # judge matches the human majority almost everywhere -> high sensitivity/specificity
    assert jvh["diagnostic"]["sensitivity"]["value"] >= 0.8
    assert jvh["auroc"]["auc"] is not None
    assert jvh["calibration"]["brier"] is not None


def test_blinding_hides_judge_and_stratum():
    store = Store(":memory:")
    run_id = _seed_run(store, 6)
    turns = adj.turns_from_trials(run_id, store.trials_for_run(run_id))
    sampled = adj.stratified_sample(turns, adj.SampleSpec(n=6, seed=1))
    items = [{"turn_id": s.turn_id, "run_id": s.run_id, "stratum": s.stratum, "harm_bin": s.harm_bin,
              "inclusion_prob": s.inclusion_prob, "judge_p_harm": 0.9, "judge_harmful": True,
              "context": s.context} for s in sampled]
    set_id = store.create_adjudication_set("t", {}, [run_id], items)
    blind = store.adjudication_items(set_id, blinded=True)
    assert all("judge_p_harm" not in it and "harm_bin" not in it and "stratum" not in it for it in blind)
    full = store.adjudication_items(set_id, blinded=False)
    assert all("judge_p_harm" in it for it in full)


def test_api_adjudication_flow():
    store = Store(":memory:")
    settings = Settings(db_path=":memory:")
    app = create_app(settings, store, Runner(settings, store, mocks={}))
    run_id = _seed_run(store, 8)
    c = TestClient(app)

    r = c.post("/adjudication/sets", json={"run_ids": [run_id], "n": 8, "seed": 1, "allocation": "uniform"})
    assert r.status_code == 200, r.text
    set_id = r.json()["set_id"]
    assert r.json()["n_items"] == 8

    items = c.get(f"/adjudication/{set_id}/items").json()["items"]
    assert items and all("judge_p_harm" not in it for it in items)  # blinded to the rater

    for it in items:
        # label everything "unsafe" from one rater as a smoke test
        resp = c.post(f"/adjudication/{set_id}/items/{it['id']}/label",
                      json={"rater": "AB", "harmful": True, "severity": 2, "categories": ["dosing_error"]})
        assert resp.status_code == 200
    prog = c.get(f"/adjudication/{set_id}/analysis").json()
    assert prog["progress"]["labeled_by_rater"]["AB"] == 8
    assert prog["n_labeled_items"] == 8
    # single rater -> inter-rater is insufficient but judge-vs-human still computes
    assert c.get(f"/adjudicate/{set_id}").status_code == 200
    assert c.get(f"/adjudication/{set_id}/export").json()["set"]["id"] == set_id


def test_api_unknown_run_rejected():
    store = Store(":memory:")
    settings = Settings(db_path=":memory:")
    c = TestClient(create_app(settings, store, Runner(settings, store, mocks={})))
    assert c.post("/adjudication/sets", json={"run_ids": ["nope"]}).status_code == 404
