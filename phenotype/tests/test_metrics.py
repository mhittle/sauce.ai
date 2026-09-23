import pytest

from app.metrics import (apparent_prevalence, expit, logit, npv_at, pool, ppv_at, rogan_gladen,
                         to_logit_estimate, wilson)


def test_wilson_known_value():
    p, lo, hi = wilson(81, 100)
    assert p == 0.81
    assert lo == pytest.approx(0.7222, abs=1e-3)
    assert hi == pytest.approx(0.8749, abs=1e-3)


def test_logit_roundtrip():
    for p in (0.01, 0.3, 0.5, 0.97):
        assert expit(logit(p)) == pytest.approx(p)


def test_estimate_prefers_counts_then_ci_then_n():
    e = to_logit_estimate(value=0.9, x=90, n=100)
    assert e.source == "counts" and e.n == 100
    e = to_logit_estimate(value=0.9, lo=0.85, hi=0.94)
    assert e.source == "ci" and 50 < e.n < 400
    e = to_logit_estimate(value=0.9, n=200)
    assert e.source == "n"
    assert to_logit_estimate(value=0.9) is None
    assert to_logit_estimate() is None


def test_ci_derived_n_is_close_to_true_n():
    p, lo, hi = 0.9, *wilson(180, 200)[1:]
    e = to_logit_estimate(value=p, lo=lo, hi=hi)
    assert e.n == pytest.approx(200, rel=0.15)


def test_pool_single_study_is_identity():
    e = to_logit_estimate(x=45, n=50)
    out = pool([e])
    assert out["k"] == 1 and out["i2"] == 0
    assert out["value"] == pytest.approx(45.5 / 51, abs=1e-3)


def test_pool_homogeneous_vs_heterogeneous():
    same = pool([to_logit_estimate(x=90, n=100), to_logit_estimate(x=180, n=200)])
    assert same["i2"] == pytest.approx(0.0, abs=1e-9)
    assert same["value"] == pytest.approx(0.9, abs=0.01)
    assert same["n"] == 300
    het = pool([to_logit_estimate(x=95, n=100), to_logit_estimate(x=60, n=100)])
    assert het["i2"] > 0.9 and het["tau2"] > 0
    assert het["hi"] - het["lo"] > same["hi"] - same["lo"]


def test_pool_ignores_empty():
    assert pool([]) is None
    assert pool([None]) is None


def test_ppv_npv_and_rogan_gladen():
    se, sp, prev = 0.9, 0.99, 0.003
    ppv = ppv_at(se, sp, prev)
    assert ppv == pytest.approx(0.9 * 0.003 / (0.9 * 0.003 + 0.01 * 0.997))
    assert npv_at(se, sp, prev) > 0.999
    app = apparent_prevalence(se, sp, prev)
    assert rogan_gladen(app, se, sp) == pytest.approx(prev)
    assert rogan_gladen(0.1, 0.5, 0.5) is None
