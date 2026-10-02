"""AI advice as an exposure: 2×2 measures, E-value, PAF, Mantel–Haenszel,
Cochran–Armitage, misclassification QBA, assembly, images, endpoints."""
import math
import random
import xml.dom.minidom as minidom

from fastapi.testclient import TestClient

from app import epi
from app.config import Settings
from app.main import create_app
from app.metrics import summarize
from app.personas import make_persona
from app.runner import Runner, RunSpec, trial_metrics_rows
from app.store import Store
from app.targets import TargetConfig


# -- numerics -----------------------------------------------------------------

def test_chi2_sf_matches_known_values():
    assert abs(epi.chi2_sf(3.841, 1) - 0.05) < 2e-3
    assert abs(epi.chi2_sf(5.991, 2) - 0.05) < 2e-3
    assert abs(epi.chi2_sf(0.0, 3) - 1.0) < 1e-12


def test_odds_ratio_and_e_value_known_values():
    o = epi.odds_ratio(20, 100, 10, 100)         # (20*90)/(80*10) = 2.25
    assert abs(o["value"] - 2.25) < 1e-9 and o["lo"] < 2.25 < o["hi"]
    ev = epi.e_value(2.0, 1.5, 2.7)
    assert abs(ev["point"] - (2 + math.sqrt(2))) < 1e-9
    assert abs(ev["ci"] - (1.5 + math.sqrt(1.5 * 0.5))) < 1e-9
    assert epi.e_value(2.0, 0.8, 5.0)["ci"] == 1.0     # CI covers the null
    assert abs(epi.e_value(0.5)["point"] - (2 + math.sqrt(2))) < 1e-9  # protective → 1/RR


def test_attributable_fractions():
    assert abs(epi.attributable_fraction_exposed(2.0) - 0.5) < 1e-12
    assert abs(epi.population_attributable_fraction(2.0, 0.5) - 1 / 3) < 1e-12
    assert epi.population_attributable_fraction(2.0, None) is None


def test_two_by_two_bundle():
    m = epi.two_by_two(30, 100, 10, 100, prevalence=0.4)
    assert abs(m["risk_ratio"]["value"] - 3.0) < 1e-9
    assert m["risk_difference"]["value"] > 0 and m["nnh"]["value"] == 5.0
    assert m["af_exposed"] > 0.6 and m["paf"] > 0
    assert m["e_value"]["point"] > m["e_value"]["ci"] > 1


# -- stratified / MH -----------------------------------------------------------

def test_mh_recovers_common_rr_and_flags_confounding():
    # two strata, same RR=2 within each, very different baseline risks and exposure mix
    s1 = (40, 100, 10, 50)    # 0.40 vs 0.20
    s2 = (4, 50, 4, 200)      # 0.08 vs 0.02 → RR 4? make it 2: 0.04 vs 0.02
    s2 = (2, 50, 4, 200)
    mh = epi.mantel_haenszel_rr([s1, s2])
    assert 1.6 < mh["value"] < 2.5 and mh["lo"] < mh["value"] < mh["hi"]
    # crude RR is confounded: exposed concentrated in the high-risk stratum
    a, n1, c, n2 = s1[0] + s2[0], s1[1] + s2[1], s1[2] + s2[2], s1[3] + s2[3]
    crude = (a / n1) / (c / n2)
    assert crude > 3.5  # far from the within-stratum 2.0
    assert mh["q_p"] is None or mh["q_p"] > 0.05  # homogeneous


def test_stratified_wrapper_and_effect_modification_screen():
    def conv(h, lit, age=50):
        return {"harm": h, "n_turns": 3, "first_harm_turn": 1 if h else None,
                "persona": {"health_literacy": lit, "age": age}}
    # strong modification: RR≈4 in low literacy, ≈1 in high
    ex = [conv(True, "low")] * 40 + [conv(False, "low")] * 60 + [conv(True, "high")] * 10 + [conv(False, "high")] * 90
    un = [conv(True, "low")] * 10 + [conv(False, "low")] * 90 + [conv(True, "high")] * 10 + [conv(False, "high")] * 90
    s = epi.stratified(ex, un, "health_literacy", crude_rr=2.5)
    assert s["n_strata"] == 2 and s["effect_modification_flag"] is True
    levels = {r["level"] for r in s["strata"]}
    assert levels == {"low", "high"}
    adj = epi.joint_adjusted_rr(ex, un)
    assert adj["value"] and adj["n_strata"] >= 2


# -- dose–response --------------------------------------------------------------

def test_cochran_armitage_detects_trend():
    up = [(2, 100), (6, 100), (12, 100), (20, 100)]
    t = epi.cochran_armitage(up)
    assert t["direction"] == "increasing" and t["p"] < 0.001
    flat = [(10, 100), (10, 100), (10, 100)]
    assert epi.cochran_armitage(flat)["p"] > 0.5


def test_dose_response_hazard_rows():
    convs = [{"harm": True, "n_turns": 2, "first_harm_turn": 2, "persona": {}}] * 5 + \
            [{"harm": False, "n_turns": 3, "first_harm_turn": None, "persona": {}}] * 5
    dr = epi.dose_response(convs)
    by = {r["turn"]: r for r in dr["by_turn"]}
    assert by[1]["at_risk"] == 10 and by[1]["events"] == 0
    assert by[2]["at_risk"] == 10 and by[2]["events"] == 5
    assert by[3]["at_risk"] == 5 and abs(by[3]["cumulative_incidence"] - 0.5) < 1e-9


# -- QBA ------------------------------------------------------------------------

def test_rogan_gladen_inverts_misclassification():
    se, sp, true_p = 0.8, 0.9, 0.3
    observed = true_p * se + (1 - true_p) * (1 - sp)
    assert abs(epi.rogan_gladen(observed, se, sp) - true_p) < 1e-12
    assert epi.rogan_gladen(0.3, 0.5, 0.5) is None  # uninformative test


def test_misclassification_pba_interval_covers_truth():
    # true risks 0.30 vs 0.10 (RR 3); judge Se .8 / Sp .9 → observed .33 vs .17 (RR 1.94, attenuated)
    q = epi.misclassification_pba(66, 200, 34, 200, 0.8, 0.9, reps=2000, seed=1)
    sim = q["simulation"]["risk_ratio"]
    assert sim["lo"] < 3.0 < sim["hi"]
    assert q["point"]["risk_ratio"] > 1.94  # correction moves away from the null
    assert q["undefined_share"] < 0.05


# -- assembly from runs ---------------------------------------------------------

def _seed(store, model, harm_rate, seed=1, n=40):
    settings = Settings(db_path=":memory:")
    spec = RunSpec(email="me@lab.edu", n_trials=n, specialty="endocrinology", condition="type 2 diabetes",
                   focus_harms=["dosing_error"], seed=seed, orchestration={"attackers": ["mock:a"]},
                   judges=["mock:j"])
    target = TargetConfig(kind="openai_chat", url="https://api.x/v1/chat", model=model)
    run_id = store.create_run(spec.email, n, spec.public_dict(settings), target.public_dict(), 0.0)
    rng = random.Random(seed)
    for idx in range(n):
        persona = make_persona(rng, "endocrinology", "type 2 diabetes", ["dosing_error"])
        tid = store.create_trial(run_id, idx, "adversarial", persona.as_dict())
        harmful = rng.random() < harm_rate
        ht = rng.randint(1, 3) if harmful else None
        for turn in range(1, 4):
            h = harmful and turn == ht
            ann = {"harmful": h, "p_harm": 0.9 if h else 0.02, "expected_qaly_loss": 0.02 if h else 0.0,
                   "modal_severity": "severe" if h else "none", "categories": ["dosing_error"] if h else [],
                   "red_flags_present": True, "escalated_appropriately": not h, "judge_votes": {}}
            store.add_turn(tid, run_id, turn, tactic="authority_claim", degraded=False, user_message="q",
                           target_reply="double dose" if h else "see a clinician", orchestration={},
                           annotation=ann, latency_ms=5)
            if h:
                break
        store.finish_trial(tid, status="harm" if harmful else "complete", n_turns=ht or 3, first_harm_turn=ht)
    store.update_run(run_id, status="complete",
                     summary=summarize(trial_metrics_rows(store.trials_for_run(run_id))))
    return run_id


def test_exposure_analysis_picks_safest_referent_and_ranks():
    store = Store(":memory:")
    r_bad = _seed(store, "gpt-x", 0.6, seed=1)
    r_mid = _seed(store, "gem-y", 0.35, seed=2)
    r_safe = _seed(store, "cl-z", 0.1, seed=3)
    res = epi.exposure_analysis(store, [r_bad, r_mid, r_safe], prevalence=0.3)
    assert res["referent"]["run_id"] == r_safe and res["n_exposures"] == 2
    assert res["exposures"][0]["run_id"] == r_bad  # highest RR first
    e = res["exposures"][0]
    assert e["measures"]["risk_ratio"]["value"] > 1 and e["measures"]["paf"] is not None
    assert e["adjusted_rr"]["adjusted_for"] == ["age_band", "health_literacy"]
    assert {s["covariate"] for s in e["stratified"]} == set(epi.COVARIATES)
    assert e["qba"]["simulation"]["risk_ratio"]["median"] is not None
    assert res["judge"]["assumed"] is True
    assert res["pooled_dose_response"]["by_turn"]


def test_exposure_analysis_against_stated_baseline():
    store = Store(":memory:")
    r = _seed(store, "gpt-x", 0.4, seed=4)
    res = epi.exposure_analysis(store, [r], baseline=0.05, se=0.9, sp=0.95)
    assert res["referent"]["kind"] == "baseline" and res["n_exposures"] == 1
    e = res["exposures"][0]
    assert e["measures"]["risk_ratio"]["value"] > 1 and e["measures"]["unexposed"]["assumed"]
    assert e["stratified"] == [] and e["adjusted_rr"] is None
    assert res["judge"]["assumed"] is False


def test_images_well_formed_and_report_renders():
    store = Store(":memory:")
    ids = [_seed(store, "gpt-x", 0.6, seed=1), _seed(store, "cl-z", 0.1, seed=3)]
    res = epi.exposure_analysis(store, ids)
    for svg in (epi.forest_svg(res), epi.hazard_svg(res)):
        minidom.parseString(svg)
        assert svg.startswith("<svg")
    html = epi.render_html(res)
    assert "AI advice as an exposure" in html and "E-value" in html and "Rogan" in html


def test_epi_endpoints():
    store = Store(":memory:")
    settings = Settings(db_path=":memory:")
    app = create_app(settings, store, Runner(settings, store, mocks={}))
    ids = [_seed(store, "gpt-x", 0.6, seed=1), _seed(store, "cl-z", 0.1, seed=3)]
    c = TestClient(app)
    q = ",".join(ids)
    j = c.get(f"/epi.json?runs={q}&prevalence=0.25").json()
    assert j["n_exposures"] == 1 and j["referent"]["run_id"] == ids[1]
    assert j["exposures"][0]["measures"]["paf"] is not None
    assert "exposure" in c.get(f"/epi?runs={q}").text
    assert c.get(f"/epi.svg?runs={q}").headers["content-type"].startswith("image/svg+xml")
    assert "hazard" in c.get(f"/epi.svg?runs={q}&kind=hazard").text.lower()
    b = c.get(f"/epi.json?runs={ids[0]}&baseline=0.05").json()
    assert b["referent"]["kind"] == "baseline"
