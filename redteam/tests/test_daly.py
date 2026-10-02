"""DALY burden probabilistic sensitivity analysis: PSA, report, endpoints."""
import random
import xml.dom.minidom as minidom

from fastapi.testclient import TestClient

from app import daly
from app.config import Settings
from app.main import create_app
from app.metrics import summarize
from app.personas import make_persona
from app.runner import Runner, RunSpec, trial_metrics_rows
from app.store import Store
from app.targets import TargetConfig


# -- PSA ----------------------------------------------------------------------

def test_severity_mix_normalizes():
    mix = daly.severity_mix({"death": 2, "severe": 2, "none": 99})
    assert abs(sum(mix.values()) - 1.0) < 1e-9
    assert set(mix) == {"death", "severe"}
    assert daly.severity_mix({}) == {"moderate": 1.0}  # fallback


def test_psa_credible_interval_ordered_and_positive():
    r = daly.psa({"death": 3, "severe": 5, "moderate": 10}, trials=100,
                 trials_with_harm=30, mean_age=45, draws=2000, seed=1)
    s = r["dalys_per_1000_conversations"]
    assert s["lo"] <= s["median"] <= s["hi"]
    assert s["mean"] > 0
    assert sum(r["hist"]["counts"]) == 2000


def test_psa_severity_sensitivity():
    fatal = daly.psa({"death": 10}, 100, 30, 45, draws=2000, seed=2)
    mild = daly.psa({"mild": 10}, 100, 30, 45, draws=2000, seed=2)
    assert fatal["dalys_per_1000_conversations"]["mean"] > \
        20 * mild["dalys_per_1000_conversations"]["mean"]  # a death dwarfs mild harm


def test_psa_harm_rate_scales_burden():
    hi = daly.psa({"severe": 10}, 100, 60, 45, draws=2000, seed=3)
    lo = daly.psa({"severe": 10}, 100, 10, 45, draws=2000, seed=3)
    assert hi["dalys_per_1000_conversations"]["mean"] > lo["dalys_per_1000_conversations"]["mean"]


def test_psa_deterministic_with_seed():
    a = daly.psa({"severe": 5}, 100, 20, 50, draws=500, seed=7)
    b = daly.psa({"severe": 5}, 100, 20, 50, draws=500, seed=7)
    assert a["dalys_per_1000_conversations"] == b["dalys_per_1000_conversations"]


def test_psa_skipped_without_trials():
    assert daly.psa({}, trials=0, trials_with_harm=0)["status"] == "skipped"


def test_density_svg_well_formed():
    r = daly.psa({"severe": 5, "death": 2}, 100, 25, 50, draws=800, seed=1)
    svg = daly.density_svg(r["hist"], r["dalys_per_1000_conversations"])
    minidom.parseString(svg)
    assert svg.startswith("<svg") and "DALYs per 1,000" in svg


# -- report + API -------------------------------------------------------------

def _seed(store, harm_rate=0.4, seed=1):
    settings = Settings(db_path=":memory:")
    spec = RunSpec(email="me@lab.edu", n_trials=30, specialty="endocrinology",
                   focus_harms=["dosing_error"], seed=seed,
                   orchestration={"attackers": ["mock:a"]}, judges=["mock:j"])
    target = TargetConfig(kind="openai_chat", url="https://api.x/v1/chat", model="bot-x")
    run_id = store.create_run(spec.email, 30, spec.public_dict(settings), target.public_dict(), 0.0)
    rng = random.Random(seed)
    for idx in range(30):
        persona = make_persona(rng, "endocrinology", None, ["dosing_error"])
        tid = store.create_trial(run_id, idx, "adversarial", persona.as_dict())
        harmful = idx < int(round(harm_rate * 30))
        sev = "death" if (harmful and idx % 5 == 0) else ("severe" if harmful else "none")
        ann = {"harmful": harmful, "p_harm": 0.9 if harmful else 0.02,
               "expected_qaly_loss": 0.05 if harmful else 0.0, "modal_severity": sev,
               "categories": ["dosing_error"] if harmful else [], "red_flags_present": True,
               "escalated_appropriately": not harmful, "judge_votes": {}}
        store.add_turn(tid, run_id, 1, tactic="authority_claim", degraded=False, user_message="q",
                       target_reply="double dose" if harmful else "ok", orchestration={},
                       annotation=ann, latency_ms=5)
        store.finish_trial(tid, status="harm" if harmful else "complete", n_turns=1,
                           first_harm_turn=1 if harmful else None)
    store.update_run(run_id, status="complete",
                     summary=summarize(trial_metrics_rows(store.trials_for_run(run_id))))
    return run_id


def test_daly_report_uses_run_data():
    store = Store(":memory:")
    rid = _seed(store, harm_rate=0.4)
    rep = daly.daly_report(store, rid)
    assert rep["target_label"] == "bot-x"
    assert rep["status"] == "ok"
    assert rep["dalys_per_1000_conversations"]["mean"] > 0
    assert 0 < rep["mean_age"] < 120  # pulled from personas
    assert daly.daly_report(store, "ghost") is None


def test_daly_endpoints():
    store = Store(":memory:")
    settings = Settings(db_path=":memory:")
    app = create_app(settings, store, Runner(settings, store, mocks={}))
    rid = _seed(store)
    c = TestClient(app)
    j = c.get(f"/runs/{rid}/daly.json").json()
    assert j["dalys_per_1000_conversations"]["lo"] <= j["dalys_per_1000_conversations"]["hi"]
    html = c.get(f"/runs/{rid}/daly").text
    assert "expected harm burden" in html and "credible interval" in html
    svg = c.get(f"/runs/{rid}/daly.svg")
    assert svg.headers["content-type"].startswith("image/svg+xml") and svg.text.startswith("<svg")
    assert c.get("/runs/ghost/daly.json").status_code == 404
