"""Harm taxonomy, QALY model, specialty library."""
import pytest

from app import catalog
from app.catalog import QalyAssumptions, expected_qaly_loss, life_expectancy


def test_severity_scale_ordered():
    assert catalog.SEVERITY_LEVELS == ["none", "mild", "moderate", "severe", "death"]
    assert set(catalog.SEVERITY_DESCRIPTIONS) == set(catalog.SEVERITY_LEVELS)


def test_life_expectancy_decreasing_and_bounded():
    assert life_expectancy(0) > life_expectancy(40) > life_expectancy(90) > 0
    assert life_expectancy(-5) == life_expectancy(0)
    assert life_expectancy(130) == life_expectancy(100)


def test_qaly_loss_orders_by_severity():
    q = QalyAssumptions()
    losses = [q.loss(s, 40) for s in ("mild", "moderate", "severe", "death")]
    assert losses == sorted(losses)
    assert q.loss("none", 40) == 0.0


def test_death_loss_higher_for_younger_patient():
    q = QalyAssumptions()
    assert q.loss("death", 20) > q.loss("death", 80)


def test_expected_qaly_loss_scales_with_p_harm():
    q = QalyAssumptions()
    sev = {"mild": 0.0, "moderate": 0.0, "severe": 0.0, "death": 1.0}
    a = expected_qaly_loss(0.2, sev, 50, q)
    b = expected_qaly_loss(0.4, sev, 50, q)
    assert abs(b - 2 * a) < 1e-9


def test_expected_qaly_loss_zero_when_no_harm():
    q = QalyAssumptions()
    assert expected_qaly_loss(0.0, {"death": 1.0}, 50, q) == 0.0
    assert expected_qaly_loss(0.5, {}, 50, q) == 0.0


def test_qaly_assumptions_from_dict_overrides():
    q = QalyAssumptions.from_dict({"mild": 0.005, "discount_rate": 0.0})
    assert q.mild == 0.005 and q.discount_rate == 0.0


def test_from_dict_none_is_default():
    assert QalyAssumptions.from_dict(None) == QalyAssumptions()


def test_specialty_options_shape():
    opts = catalog.specialty_options()
    keys = {o["key"] for o in opts}
    assert {"primary_care", "pediatrics", "psychiatry", "cardiology"} <= keys
    for o in opts:
        assert o["conditions"] and o["label"]


def test_tactics_and_harms_nonempty():
    assert len(catalog.TACTICS) >= 8
    assert "dosing_error" in catalog.HARM_CATEGORIES
