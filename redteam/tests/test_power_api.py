"""Power calculator endpoint."""
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.runner import Runner
from app.store import Store


def _client():
    store = Store(":memory:")
    settings = Settings(db_path=":memory:")
    return TestClient(create_app(settings, store, Runner(settings, store, mocks={})))


def test_precision_applies_design_effect():
    c = _client()
    plain = c.get("/power.json?mode=precision&p=0.1&half_width=0.03&cluster_size=1&icc=0").json()
    clustered = c.get("/power.json?mode=precision&p=0.1&half_width=0.03&cluster_size=6&icc=0.1").json()
    assert clustered["design_effect"] == 1.5
    assert clustered["n"] > plain["n"]


def test_two_proportions_and_mde_and_burden():
    c = _client()
    tp = c.get("/power.json?mode=two_proportions&p1=0.5&p2=0.3&cluster_size=1&icc=0").json()
    assert 176 <= tp["total"] <= 196
    mde = c.get("/power.json?mode=mde&p1=0.2&n_per_group=200&cluster_size=1&icc=0").json()
    assert 0 < mde["mde_abs"] < 0.2
    burden = c.get("/power.json?mode=review_burden&n_valid=1000&screen_positive_rate=0.05&neg_sample_rate=0.1").json()
    assert burden["expected_reviewed"] == 145 and burden["clinician_labels"] == 290
    r3 = c.get("/power.json?mode=rule_of_three&target_upper=0.01").json()
    assert r3["n"] == 300


def test_bad_mode_and_missing_n():
    c = _client()
    assert c.get("/power.json?mode=nonsense").status_code == 400
    assert c.get("/power.json?mode=mde&n_per_group=0").status_code == 400
    assert c.get("/power").status_code == 200
