"""Agreement, diagnostic-accuracy, and calibration estimators."""
import math

from app import agreement as A


def test_cohen_kappa_perfect_and_chance():
    assert A.cohen_kappa([1, 0, 1, 0], [1, 0, 1, 0]) == 1.0
    # total disagreement on a balanced 2-class problem → negative kappa
    assert A.cohen_kappa([1, 1, 0, 0], [0, 0, 1, 1]) < 0
    assert A.cohen_kappa([], []) is None


def test_cohen_kappa_known_value():
    # 2x2: a=[1]*8+[0]*12 vs b matched except a few flips
    a = [1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    b = [1, 1, 1, 1, 1, 1, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    k = A.cohen_kappa(a, b)
    assert 0.4 < k < 0.75


def test_gwet_ac1_beats_kappa_on_rare_label():
    # 18 agree "no", 1 agree "yes", 1 disagreement → high agreement, but
    # kappa collapses under the paradox while AC1 stays high.
    a = [0] * 18 + [1, 0]
    b = [0] * 18 + [0, 1]
    k = A.cohen_kappa(a, b)
    ac1 = A.gwet_ac1(a, b)
    assert ac1 > 0.8
    assert ac1 > (k if k is not None else -1)


def test_weighted_kappa_ordinal():
    sev_a = [0, 1, 2, 3, 4, 2, 1]
    sev_b = [0, 1, 2, 3, 4, 2, 1]
    assert A.weighted_kappa(sev_a, sev_b, "quadratic", categories=[0, 1, 2, 3, 4]) == 1.0
    near = A.weighted_kappa([0, 1, 2, 3, 4], [1, 2, 3, 4, 4], "linear", categories=[0, 1, 2, 3, 4])
    assert near is not None and near < 1.0


def test_diagnostic_counts_and_rates():
    pred = [True, True, False, False, True]
    truth = [True, False, False, True, True]
    d = A.diagnostic(pred, truth)
    assert (d["tp"], d["fp"], d["fn"], d["tn"]) == (2, 1, 1, 1)
    assert abs(d["sensitivity"]["value"] - 2 / 3) < 1e-9
    assert abs(d["specificity"]["value"] - 1 / 2) < 1e-9
    assert d["sensitivity"]["lo"] <= d["sensitivity"]["value"] <= d["sensitivity"]["hi"]


def test_roc_auc_perfect_and_half():
    scores = [0.1, 0.2, 0.8, 0.9]
    truth = [False, False, True, True]
    assert A.roc_auc(scores, truth)["auc"] == 1.0
    # tied scores across classes → 0.5
    assert A.roc_auc([0.5, 0.5, 0.5, 0.5], [True, False, True, False])["auc"] == 0.5


def test_roc_auc_matches_rank_definition():
    scores = [0.2, 0.4, 0.35, 0.8]
    truth = [False, True, False, True]
    # pairs (neg,pos): (0.2,0.4)+, (0.2,0.8)+, (0.35,0.4)+, (0.35,0.8)+ = 4/4
    assert A.roc_auc(scores, truth)["auc"] == 1.0


def test_brier_and_ece():
    probs = [0.9, 0.8, 0.2, 0.1]
    truth = [True, True, False, False]
    b = A.brier_score(probs, truth)
    assert 0 < b < 0.05
    ece = A.expected_calibration_error(probs, truth, n_bins=5)
    assert 0 <= ece < 0.2


def test_reliability_bins_cover_predictions():
    probs = [0.05, 0.15, 0.95]
    truth = [False, False, True]
    bins = A.reliability_bins(probs, truth, n_bins=10)
    assert sum(b["n"] for b in bins) == 3
    assert bins[-1]["observed"] == 1.0  # the 0.95 case landed in the top bin and was positive


def test_perfect_calibration_zero_ece():
    # 10 items at p=1 all positive, 10 at p=0 all negative
    probs = [1.0] * 10 + [0.0] * 10
    truth = [True] * 10 + [False] * 10
    assert A.expected_calibration_error(probs, truth) == 0.0
    assert A.brier_score(probs, truth) == 0.0


def test_majority_vote_and_ties():
    assert A.majority_vote([True, True, False]) is True
    assert A.majority_vote([True, False]) is None  # tie
    assert A.majority_vote([False, False, False]) is False


def test_fleiss_kappa_perfect():
    assert A.fleiss_kappa([[True, True, True], [False, False, False]] * 3) == 1.0
