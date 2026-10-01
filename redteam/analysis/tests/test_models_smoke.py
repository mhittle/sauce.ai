"""End-to-end smoke test for the confirmatory models.

Skipped unless the scientific stack is installed, so it is a no-op under the
stdlib ``redteam-ci`` check and runs for real under ``analysis-ci`` (and on a
researcher's machine). It asserts the SAP runs on simulated data and recovers
the planted target signal, not exact coefficients.
"""
import pytest

pytest.importorskip("pandas")
pytest.importorskip("statsmodels")
pytest.importorskip("lifelines")

from analysis import sap, simulate  # noqa: E402


def _results():
    rows = simulate.generate(n_targets=4, trials_per_target=120, seed=11)
    return sap.run_all(rows)


def test_run_all_ok():
    r = _results()
    assert r["status"] == "ok"
    assert r["n_targets"] == 4
    for key in ("primary_logistic", "time_to_harm_km", "discrete_time_hazard",
                "competing_risks", "fdr_target_contrasts"):
        assert key in r


def test_primary_logistic_recovers_target_ordering():
    r = _results()
    gee = r["primary_logistic"]["gee"]
    assert gee["status"] == "ok"
    coef = gee["coef"]
    # leakiest target (target-4) should have a higher OR vs the reference target
    # than the next-safest (target-2), both relative to target-1 (baseline).
    t4 = coef["C(target_label)[T.target-4]"]["or"]
    t2 = coef["C(target_label)[T.target-2]"]["or"]
    assert t4 > t2 > 0


def test_km_logrank_detects_difference():
    r = _results()
    km = r["time_to_harm_km"]
    assert km["status"] == "ok"
    assert km["logrank"]["p"] < 0.05  # targets differ in time-to-harm
    assert set(km["medians"]) == {"target-1", "target-2", "target-3", "target-4"}


def test_fdr_present():
    r = _results()
    fdr = r["fdr_target_contrasts"]
    assert len(fdr["terms"]) >= 1
    assert len(fdr["q"]) == len(fdr["p"])


def test_markdown_renders():
    md = sap.to_markdown(_results())
    assert "Confirmatory analysis" in md and "Kaplan" in md


def test_invalid_input_reported():
    r = sap.run_all([{"harmful": 1}])
    assert r["status"] == "invalid" and r["problems"]
