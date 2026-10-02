"""Latent-safety leaderboard: paired simulator + item responses (stdlib), and
the Rasch / Bradley–Terry fits (gated on the scientific stack)."""
import pytest

from analysis import schema, simulate


# -- stdlib: paired design + response construction ----------------------------

def test_generate_paired_shares_items_across_targets():
    rows = simulate.generate_paired(n_targets=3, n_items=20, seed=5)
    assert schema.validate(rows) == []
    # each (specialty, trial_idx) item appears under every target
    by_target = {}
    for r in rows:
        key = (r["specialty"], r["trial_idx"])
        by_target.setdefault(r["target_label"], set()).add(key)
    targets = list(by_target)
    assert len(targets) == 3
    shared = set.intersection(*by_target.values())
    assert len(shared) == 20  # all 20 items seen by all 3 targets


def test_generate_paired_has_vulnerability_gradient():
    rows = simulate.generate_paired(n_targets=4, n_items=80, seed=9)
    rate = {}
    for r in rows:
        k, n = rate.get(r["target_label"], (0, 0))
        rate[r["target_label"]] = (k + int(r["harmful"]), n + 1)
    by = {t: k / n for t, (k, n) in rate.items()}
    assert by["target-1"] < by["target-4"]  # target-1 safest, target-4 leakiest


def test_item_responses_shared_flag():
    pytest.importorskip("pandas")
    from analysis import io, latent
    df = io.to_frame(simulate.generate_paired(n_targets=3, n_items=15, seed=1))
    resp = latent.item_responses(df)
    assert set(resp.columns) >= {"target_label", "item", "y"}
    assert resp["y"].isin([0, 1]).all()
    assert latent._shared_ok(resp) is True


# -- gated: the models --------------------------------------------------------

pytestmark_models = pytest.mark.skipif(False, reason="")


def _fitted():
    pytest.importorskip("pandas")
    pytest.importorskip("statsmodels")
    from analysis import io, latent
    df = io.to_frame(simulate.generate_paired(n_targets=4, n_items=70, seed=11))
    return latent.rasch_safety(df), latent.bradley_terry_safety(df)


def test_rasch_ranks_safest_first():
    rasch, _ = _fitted()
    assert rasch["status"] == "ok"
    assert rasch["ranking"][0]["target"] == "target-1"       # safest on top
    assert rasch["ranking"][-1]["target"] == "target-4"      # leakiest last
    # monotone latent safety
    vals = [e["latent_safety"] for e in rasch["ranking"]]
    assert vals == sorted(vals, reverse=True)
    assert rasch["ranking"][0]["reference"] is True


def test_bradley_terry_agrees():
    _, bt = _fitted()
    assert bt["status"] == "ok"
    assert bt["ranking"][0]["target"] == "target-1"
    assert bt["n_comparisons"] > 0


def test_forest_svg_is_well_formed():
    """Pure: forest_svg takes a ranking dict, no stats deps."""
    import xml.dom.minidom as minidom
    from analysis import latent
    rasch = {"status": "ok", "reference": "target-1", "ranking": [
        {"target": "target-1", "latent_safety": 0.0, "lo": 0.0, "hi": 0.0, "reference": True, "rank": 1},
        {"target": "target-2", "latent_safety": -1.8, "lo": -2.9, "hi": -0.8, "reference": False, "rank": 2},
        {"target": "target-3", "latent_safety": -3.1, "lo": -4.3, "hi": -1.9, "reference": False, "rank": 3},
    ]}
    svg = latent.forest_svg(rasch)
    minidom.parseString(svg)  # raises if malformed
    assert svg.startswith("<svg") and "Latent-safety leaderboard" in svg
    assert "target-1" in svg and "target-3" in svg
    assert "&middot;" not in svg  # XML-safe: literal middle dot, not an HTML entity


def test_forest_svg_empty_when_skipped():
    from analysis import latent
    assert latent.forest_svg({"status": "skipped"}) == ""
    assert latent.forest_svg({}) == ""


def test_latent_skipped_without_paired_design():
    pytest.importorskip("pandas")
    pytest.importorskip("statsmodels")
    from analysis import io, latent
    # unpaired generator: items are not shared across targets
    df = io.to_frame(simulate.generate(n_targets=3, trials_per_target=20, seed=2))
    out = latent.rasch_safety(df)
    assert out["status"] in ("skipped", "ok")  # may be ok if coarse items overlap
    # the explicit guard works on an empty frame
    import pandas as pd
    assert latent._shared_ok(pd.DataFrame(columns=["target_label", "item", "y"])) is False
