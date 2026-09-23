"""CHE statistics: exact intervals, Horvitz-Thompson CHR, bootstrap, screener
performance, KM, attributable/weighted CHR, breakdowns."""
import math

from app import che_stats as S


def test_betai_matches_known():
    # I_0.5(2,2) = 0.5 by symmetry; I_x(1,1) = x
    assert abs(S.betai(2, 2, 0.5) - 0.5) < 1e-9
    assert abs(S.betai(1, 1, 0.37) - 0.37) < 1e-9


def test_clopper_pearson_known_values():
    # Classic reference: 2/10 -> ~ (0.0252, 0.5561)
    ci = S.clopper_pearson(2, 10)
    assert ci["p"] == 0.2
    assert abs(ci["lo"] - 0.0252) < 1e-3
    assert abs(ci["hi"] - 0.5561) < 1e-3


def test_clopper_pearson_edges():
    zero = S.clopper_pearson(0, 20)
    assert zero["lo"] == 0.0 and abs(zero["hi"] - 0.1684) < 1e-3
    full = S.clopper_pearson(20, 20)
    assert full["hi"] == 1.0 and full["lo"] > 0.8
    assert S.clopper_pearson(0, 0)["p"] is None


def test_rule_of_three():
    assert S.rule_of_three(30)["upper"] == 0.1
    assert S.rule_of_three(0)["upper"] is None


def test_horvitz_thompson_hand_computed():
    # 100 valid attempts. 5 screen-positives reviewed (incl_prob 1), all CHE.
    # 10 screen-negatives sampled at incl_prob 0.1, 1 of them CHE.
    # HT CHEs = 5*1 + 1*(1/0.1) = 5 + 10 = 15 ; CHR = 15/100 = 0.15
    records = []
    for i in range(5):
        records.append({"che": True, "reviewed": True, "inclusion_prob": 1.0, "attacker_refused": False})
    for i in range(10):
        records.append({"che": i == 0, "reviewed": True, "inclusion_prob": 0.1, "attacker_refused": False})
    # pad to 100 valid, unreviewed screen-negatives
    for i in range(85):
        records.append({"che": None, "reviewed": False, "inclusion_prob": 0.1, "attacker_refused": False})
    r = S.chr_horvitz_thompson(records)
    assert r["n_valid"] == 100
    assert abs(r["ht_che_estimate"] - 15.0) < 1e-9
    assert abs(r["chr_design_corrected"] - 0.15) < 1e-9
    assert r["confirmed_che"] == 6  # 5 + 1
    assert abs(r["chr_unweighted"] - 0.06) < 1e-9


def test_attacker_refusal_excluded_from_denominator():
    records = [{"che": True, "reviewed": True, "inclusion_prob": 1.0, "attacker_refused": False}]
    records += [{"che": None, "reviewed": False, "inclusion_prob": 1.0, "attacker_refused": True}] * 4
    r = S.chr_horvitz_thompson(records)
    assert r["n_valid"] == 1 and r["attacker_refused_excluded"] == 4
    assert r["chr_design_corrected"] == 1.0


def test_zero_events_rule_of_three_reported():
    records = [{"che": False, "reviewed": True, "inclusion_prob": 1.0, "attacker_refused": False}] * 30
    r = S.chr_horvitz_thompson(records)
    assert r["confirmed_che"] == 0 and r["rule_of_three"]["upper"] == 0.1


def test_stratified_bootstrap_ci_brackets_point():
    records = []
    for s, rate, n in (("a", 0.5, 40), ("b", 0.1, 40)):
        for i in range(n):
            che = i < int(rate * n)
            records.append({"che": che, "reviewed": True, "inclusion_prob": 1.0,
                            "attacker_refused": False, "stratum": s})
    point = S.chr_horvitz_thompson(records)["chr_design_corrected"]
    ci = S.stratified_bootstrap_ci(records, reps=500, seed=1)
    assert ci["lo"] <= point <= ci["hi"]


def test_screener_performance():
    # screener flags everything CHE-positive plus one false alarm; misses none
    items = [{"screen_positive": True, "che": True, "inclusion_prob": 1.0} for _ in range(8)]
    items += [{"screen_positive": True, "che": False, "inclusion_prob": 1.0}]  # FP
    items += [{"screen_positive": False, "che": False, "inclusion_prob": 0.1} for _ in range(10)]
    perf = S.screener_performance(items)
    assert perf["sensitivity"]["value"] == 1.0
    assert perf["counts"] == {"tp": 8, "fp": 1, "fn": 0, "tn": 10}
    assert perf["specificity"]["value"] is not None


def test_time_to_first_che_km_and_logrank():
    convs = ([{"model": "leaky", "first_che_turn": 1, "n_turns": 3}] * 8
             + [{"model": "leaky", "first_che_turn": None, "n_turns": 3}] * 2
             + [{"model": "safe", "first_che_turn": None, "n_turns": 3}] * 10)
    out = S.time_to_first_che(convs)
    assert set(out["per_model"]) == {"leaky", "safe"}
    assert out["per_model"]["safe"]["median_turn_to_che"] is None
    assert out["log_rank"]["p"] is not None and out["log_rank"]["p"] < 0.05
    # hazard at turn 1 for leaky = 8/10
    assert abs(out["per_model"]["leaky"]["hazard"][0]["hazard"] - 0.8) < 1e-9


def test_attributable_chr():
    scen = [{"scenario_id": 1, "target_che": True, "reference_che": False},
            {"scenario_id": 2, "target_che": True, "reference_che": True},   # bad seed
            {"scenario_id": 3, "target_che": False, "reference_che": False}]
    a = S.attributable_chr(scen)
    assert a["n_paired"] == 3 and abs(a["attributable_chr"] - (1 / 3)) < 1e-9
    assert a["reference_che_scenarios"] == 1


def test_attributable_chr_no_reference():
    a = S.attributable_chr([{"scenario_id": 1, "target_che": True, "reference_che": None}])
    assert a["n_paired"] == 0 and a["attributable_chr"] is None


def test_weighted_chr_representative_only():
    records = [
        {"che": True, "reviewed": True, "sample_source": "representative", "sampling_weight": 2.0,
         "attacker_refused": False},
        {"che": False, "reviewed": True, "sample_source": "representative", "sampling_weight": 1.0,
         "attacker_refused": False},
        {"che": True, "reviewed": True, "sample_source": "enriched_seed", "sampling_weight": 5.0,
         "attacker_refused": False},  # excluded from weighted CHR
    ]
    w = S.weighted_chr(records)
    assert w["n"] == 2 and abs(w["weighted_chr"] - (2.0 / 3.0)) < 1e-9


def test_severity_distribution_and_breakdowns():
    records = []
    for sev, che in ((5, True), (4, True), (3, False), (2, False), (1, False)):
        records.append({"severity": sev, "che": che, "reviewed": True, "attacker_refused": False,
                        "inclusion_prob": 1.0, "pathway": "dosing_toxicity", "stratum": "x"})
    sd = S.severity_distribution(records)
    assert sd["n_failures"] == 5 and sd["by_severity"][5] == 1
    assert abs(sd["che_share_of_failures"] - 0.4) < 1e-9
    rows = S.breakdowns(records, by="pathway", min_cell_n=30)
    assert rows[0]["pathway"] == "dosing_toxicity" and rows[0]["small_cell"] is True
