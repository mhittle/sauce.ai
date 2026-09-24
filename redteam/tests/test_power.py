"""Sample-size / power calculator vs known values."""
import math

from app import power as P


def test_norm_ppf_and_cdf_roundtrip():
    assert abs(P.norm_ppf(0.975) - 1.959964) < 1e-4
    assert abs(P.norm_ppf(0.5)) < 1e-9
    assert abs(P.norm_cdf(1.959964) - 0.975) < 1e-5
    assert abs(P.norm_cdf(0) - 0.5) < 1e-12


def test_n_for_precision_exact_formula():
    # p=.2, half-width .05, 95%: n = 1.96^2 * .16 / .0025 ≈ 245.9 -> 246
    r = P.n_for_precision(0.2, 0.05)
    assert r["n"] == 246
    # design effect scales it
    r2 = P.n_for_precision(0.2, 0.05, design_effect=1.5)
    assert r2["n"] == math.ceil(246 * 1.5 / 1)  # ~369
    assert r2["n"] >= 368


def test_design_effect():
    assert P.design_effect(5, 0.1) == 1.4
    assert P.design_effect(1, 0.5) == 1.0


def test_n_two_proportions_known():
    # Classic: p1=.5, p2=.3, alpha .05, power .8 -> ~93 per group (normal approx)
    r = P.n_two_proportions(0.5, 0.3)
    assert 88 <= r["n1"] <= 98 and r["n2"] == r["n1"]
    assert r["total"] == r["n1"] + r["n2"]


def test_power_two_proportions_roundtrip():
    r = P.n_two_proportions(0.5, 0.3, power=0.80)
    ach = P.power_two_proportions(0.5, 0.3, r["n1"], r["n2"])["power"]
    assert 0.78 <= ach <= 0.88  # at/above target since n is rounded up


def test_min_detectable_difference_monotone():
    small_n = P.min_detectable_difference(0.2, 50)["mde_abs"]
    big_n = P.min_detectable_difference(0.2, 500)["mde_abs"]
    assert big_n < small_n  # more data -> smaller detectable effect
    assert 0 < big_n < 0.2


def test_two_phase_review_burden():
    b = P.two_phase_review_burden(1000, screen_positive_rate=0.05, neg_sample_rate=0.10)
    # 50 positives + 0.10*950 = 95 -> 145 reviewed, 290 clinician labels
    assert b["expected_positive"] == 50
    assert b["expected_reviewed"] == 145
    assert b["clinician_labels"] == 290


def test_rule_of_three_n():
    assert P.rule_of_three_n(0.01)["n"] == 300
    assert P.rule_of_three_n(0.0)["n"] is None
