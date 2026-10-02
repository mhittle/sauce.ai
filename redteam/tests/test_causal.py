"""Causal DAG toolkit: d-separation, backdoor criterion, minimal adjustment
sets, reference DAGs, SVG."""
import xml.dom.minidom as minidom

import pytest

from app import causal


def _g(edges, unobserved=()):
    ids = {n for e in edges for n in e}
    nodes = {n: {"label": n, "kind": "unobserved" if n in unobserved else "covariate"} for n in ids}
    nodes["X"]["kind"] = "exposure"
    nodes["Y"]["kind"] = "outcome"
    return causal.DAG(nodes, edges)


def test_d_separation_textbook_cases():
    # chain X→M→Y: blocked by M
    g = _g([("X", "M"), ("M", "Y")])
    assert not g.d_separated("X", "Y", set()) and g.d_separated("X", "Y", {"M"})
    # fork X←C→Y: blocked by C
    g = _g([("C", "X"), ("C", "Y")])
    assert not g.d_separated("X", "Y", set()) and g.d_separated("X", "Y", {"C"})
    # collider X→K←Y: open only when conditioning on K (or its descendant)
    g = _g([("X", "K"), ("Y", "K"), ("K", "D")])
    assert g.d_separated("X", "Y", set())
    assert not g.d_separated("X", "Y", {"K"}) and not g.d_separated("X", "Y", {"D"})


def test_backdoor_and_minimal_sets_classic_confounding():
    g = _g([("C", "X"), ("C", "Y"), ("X", "Y"), ("X", "M"), ("M", "Y")])
    assert g.minimal_adjustment_sets("X", "Y") == [["C"]]
    assert not g.backdoor_valid("X", "Y", {"M"})     # mediator is a descendant of X
    assert not g.backdoor_valid("X", "Y", set())


def test_m_bias_collider_is_not_an_adjustment_set():
    # X ← U1 → K ← U2 → Y, with U's unmeasured: the empty set is valid; {K} opens the path
    g = _g([("U1", "X"), ("U1", "K"), ("U2", "K"), ("U2", "Y"), ("X", "Y")], unobserved={"U1", "U2"})
    assert g.backdoor_valid("X", "Y", set()) and not g.backdoor_valid("X", "Y", {"K"})
    assert g.minimal_adjustment_sets("X", "Y") == [[]]


def test_unmeasured_confounder_not_identifiable():
    g = _g([("U", "X"), ("U", "Y"), ("C", "X"), ("C", "Y"), ("X", "Y")], unobserved={"U"})
    assert g.minimal_adjustment_sets("X", "Y") == []


def test_cycle_rejected():
    with pytest.raises(ValueError):
        _g([("X", "Y"), ("Y", "X")])


def test_reference_dags_tell_the_design_story():
    obs = causal.analyze("observational")
    assert obs["identifiable_by_adjustment"] is False  # U → A and U → Y
    assert obs["unblockable_paths_after_adjustment"]
    assert obs["measurement_bias_path"] == ["A", "J", "Ystar"]
    trial = causal.analyze("trial")
    assert trial["identifiable_by_adjustment"] is True
    assert trial["minimal_adjustment_sets"] == [[]]   # exposure assigned by design
    assert any("mediator" in n for n in trial["notes"])
    # drop the unmeasured confounding arrow → observed covariates suffice
    g = causal.DAG(causal._NODES, [e for e in causal.reference_dag("observational").edges if e != ("U", "A")])
    sets = g.minimal_adjustment_sets("A", "Y")
    assert sets and set(sets[0]) == {"Acc", "Age", "Lit", "Sev"}


def test_open_backdoor_paths_enumeration():
    obs = causal.reference_dag("observational")
    paths = obs.open_backdoor_paths("A", "Y", set())
    assert ["A", "Lit", "Y"] in paths and ["A", "U", "Y"] in paths
    assert all(p[0] == "A" and p[-1] == "Y" for p in paths)
    blocked = obs.open_backdoor_paths("A", "Y", {"Age", "Lit", "Sev", "Acc"})
    assert blocked == [["A", "U", "Y"]]


def test_dag_svg_well_formed_both_designs():
    for d in ("observational", "trial"):
        svg = causal.dag_svg(causal.analyze(d))
        minidom.parseString(svg)
        assert svg.startswith("<svg") and "Health literacy" in svg
