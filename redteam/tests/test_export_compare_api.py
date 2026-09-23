"""API for the tidy export and cross-model comparison."""
import csv
import io
import random

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.personas import make_persona
from app.runner import Runner, RunSpec
from app.store import Store
from app.targets import TargetConfig


def _seed_run(store, model, harm_rate, rid_seed=1):
    settings = Settings(db_path=":memory:")
    spec = RunSpec(email="me@lab.edu", n_trials=20, specialty="endocrinology",
                   focus_harms=["dosing_error"], seed=rid_seed,
                   orchestration={"attackers": ["mock:a"], "arbiters": ["mock:b"]}, judges=["mock:j"])
    target = TargetConfig(kind="openai_chat", url="https://api.x/v1/chat", model=model)
    run_id = store.create_run(spec.email, 20, spec.public_dict(settings), target.public_dict(), 0.0)
    rng = random.Random(rid_seed)
    for idx in range(20):
        persona = make_persona(rng, "endocrinology", None, ["dosing_error"])
        tid = store.create_trial(run_id, idx, "adversarial", persona.as_dict())
        harmful = idx < int(round(harm_rate * 20))
        ann = {"harmful": harmful, "p_harm": 0.9 if harmful else 0.02,
               "expected_qaly_loss": 0.02 if harmful else 0.0,
               "modal_severity": "severe" if harmful else "none",
               "categories": ["dosing_error"] if harmful else [], "red_flags_present": True,
               "escalated_appropriately": not harmful, "judge_votes": {}, "correct_guidance": "x",
               "rationale": "y", "evidence_quotes": []}
        store.add_turn(tid, run_id, 1, tactic="authority_claim", degraded=False, user_message="q",
                       target_reply="double dose" if harmful else "see a clinician",
                       orchestration={}, annotation=ann, latency_ms=5)
        store.finish_trial(tid, status="harm" if harmful else "complete", n_turns=1,
                           first_harm_turn=1 if harmful else None)
    return run_id


def _client():
    store = Store(":memory:")
    settings = Settings(db_path=":memory:")
    app = create_app(settings, store, Runner(settings, store, mocks={}))
    return TestClient(app), store


def test_export_tidy_csv():
    c, store = _client()
    r1 = _seed_run(store, "gpt-x", 0.2)
    r2 = _seed_run(store, "claude-sonnet-5", 0.6, rid_seed=2)
    resp = c.get(f"/export/tidy.csv?runs={r1},{r2}")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert len(rows) == 40  # 20 trials x 1 turn x 2 runs
    assert {row["target_label"] for row in rows} == {"gpt-x", "claude-sonnet-5"}
    assert "p_harm" in rows[0] and "persona_age" in rows[0] and "seed" in rows[0]


def test_export_tidy_trial_level_and_json():
    c, store = _client()
    r1 = _seed_run(store, "gpt-x", 0.5)
    csvr = c.get(f"/export/tidy.csv?runs={r1}&level=trial")
    rows = list(csv.DictReader(io.StringIO(csvr.text)))
    assert len(rows) == 20 and "any_harm" in rows[0]
    js = c.get(f"/export/tidy.json?runs={r1}").json()
    assert js["level"] == "turn" and js["n_rows"] == 20 and "columns" in js


def test_export_rejects_unknown_run():
    c, _ = _client()
    assert c.get("/export/tidy.csv?runs=nope").status_code == 404
    assert c.get("/export/tidy.csv?runs=").status_code == 400


def test_compare_endpoints():
    c, store = _client()
    r1 = _seed_run(store, "safe-bot", 0.1)
    r2 = _seed_run(store, "leaky-bot", 0.75, rid_seed=2)
    j = c.get(f"/compare.json?runs={r1},{r2}").json()
    assert j["n_targets"] == 2
    assert j["entries"][0]["target_label"] == "leaky-bot"  # most vulnerable first
    html = c.get(f"/compare?runs={r1},{r2}")
    assert html.status_code == 200 and "Cross-model comparison" in html.text
    assert "leaky-bot" in html.text
