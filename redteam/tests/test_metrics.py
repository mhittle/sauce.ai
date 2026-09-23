"""Pure metric tests: intervals, NNH, Kaplan-Meier, log-rank, kappa."""
import math

from app import metrics


def _trial(arm, turns_harm):
    """turns_harm: list of (harmful, p_harm) per turn."""
    first = next((i + 1 for i, (h, _) in enumerate(turns_harm) if h), None)
    turns = [{"harmful": h, "p_harm": p, "expected_qaly_loss": p * 0.01,
              "modal_severity": "moderate" if h else "none", "categories": ["dosing_error"] if h else [],
              "tactic": "authority_claim", "red_flags_present": False,
              "escalated_appropriately": None, "judge_votes": {"a": h, "b": h}}
             for h, p in turns_harm]
    return {"arm": arm, "n_turns": len(turns_harm), "first_harm_turn": first, "turns": turns}


def test_wilson_matches_known_value():
    p, lo, hi = metrics.wilson(2, 10)
    assert p == 0.2
    assert round(lo, 3) == 0.057 and round(hi, 3) == 0.510


def test_wilson_zero_events():
    p, lo, hi = metrics.wilson(0, 20)
    assert p == 0.0 and lo == 0.0 and hi > 0


def test_number_needed_is_inverse_risk():
    nnh = metrics.number_needed(0.25, 0.1, 0.5)
    assert nnh["value"] == 4.0
    assert nnh["hi"] == 10.0 and nnh["lo"] == 2.0


def test_risk_difference_and_nnh_positive_effect():
    rd = metrics.risk_difference(40, 100, 10, 100)
    assert abs(rd["value"] - 0.3) < 1e-9
    nnh = metrics.nnh_from_rd(rd)
    assert abs(nnh["value"] - 1 / 0.3) < 1e-9 and not nnh["note"]


def test_nnh_flags_no_excess_risk():
    rd = metrics.risk_difference(5, 100, 20, 100)
    assert metrics.nnh_from_rd(rd)["value"] is None


def test_nnh_note_when_ci_spans_zero():
    rd = metrics.risk_difference(12, 100, 10, 100)
    nnh = metrics.nnh_from_rd(rd)
    assert nnh["value"] is not None and "infinity" in nnh["note"]


def test_risk_ratio_continuity_correction_on_zero_cell():
    rr = metrics.risk_ratio(10, 50, 0, 50)
    assert rr["continuity_corrected"] and rr["value"] > 1


def test_km_curve_monotone_and_median():
    times = [1, 1, 2, 3, 3, 3, 4, 5]
    events = [True, True, True, True, True, True, False, False]
    km = metrics.kaplan_meier(times, events)
    surv = [p["s"] for p in km["curve"]]
    assert surv == sorted(surv, reverse=True)
    assert km["median"] is not None and km["rmst"] <= km["horizon"]


def test_km_no_events_survival_flat():
    km = metrics.kaplan_meier([3, 3, 3], [False, False, False])
    assert km["median"] is None
    assert all(p["s"] == 1.0 for p in km["curve"])


def test_log_rank_detects_separation():
    t1, e1 = [1, 1, 2, 2], [True] * 4
    t2, e2 = [5, 5, 5, 5], [False] * 4
    lr = metrics.log_rank(t1, e1, t2, e2)
    assert lr["p"] is not None and lr["p"] < 0.05


def test_fleiss_kappa_perfect_agreement():
    assert metrics.fleiss_kappa([[True, True], [False, False]] * 3) == 1.0


def test_fleiss_kappa_bounds():
    k = metrics.fleiss_kappa([[True, False], [False, True], [True, True], [False, False]])
    assert -1.0 <= k <= 1.0


def test_poisson_ci_contains_estimate():
    lo, hi = metrics.poisson_ci(5)
    assert lo < 5 < hi


def test_bootstrap_ci_brackets_mean():
    xs = [0.1, 0.2, 0.3, 0.4, 0.5]
    out = metrics.mean_ci_bootstrap(xs, reps=500, seed=1)
    assert out["lo"] <= out["mean"] <= out["hi"]
    assert abs(out["mean"] - 0.3) < 1e-9


def test_summarize_two_arms():
    trials = ([_trial("adversarial", [(False, 0.05), (True, 0.8)]) for _ in range(15)]
              + [_trial("adversarial", [(False, 0.02), (False, 0.03)]) for _ in range(5)]
              + [_trial("control", [(False, 0.01), (False, 0.02)]) for _ in range(20)])
    s = metrics.summarize(trials)
    assert s["adversarial"]["trials"] == 20
    assert s["adversarial"]["trials_with_harm"] == 15
    assert s["control"]["trials_with_harm"] == 0
    assert s["comparison"]["risk_ratio"]["value"] > 1
    assert s["comparison"]["nnh"]["value"] is not None
    assert s["judge_agreement"]["fleiss_kappa"] == 1.0
    assert s["adversarial"]["category_counts"].get("dosing_error") == 15


def test_summarize_single_arm_no_comparison():
    s = metrics.summarize([_trial("adversarial", [(True, 0.9)]) for _ in range(5)])
    assert s["comparison"] is None and s["control"] is None
    assert s["adversarial"]["nnh_conversations"]["value"] == 1.0
