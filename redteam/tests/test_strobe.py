"""STROBE-style reporting checklist auto-populated from the instrument."""
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, "tests")
from test_epi import _seed, _adjudicate  # noqa: E402

from app import strobe  # noqa: E402
from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.runner import Runner  # noqa: E402
from app.store import Store  # noqa: E402


def test_checklist_has_22_items_and_scores_applicable_only():
    store = Store(":memory:")
    ids = [_seed(store, "gpt-x", 0.5, seed=1), _seed(store, "cl-z", 0.2, seed=1)]
    res = strobe.checklist(store, ids)
    assert len(res["items"]) == 22 and [i["n"] for i in res["items"]] == list(range(1, 23))
    sc = res["score"]
    assert sc["applicable"] == 21  # funding is n/a
    assert sc["reported"] + sc["partial"] + sc["missing"] == sc["applicable"]
    assert 0 < sc["share_reported"] <= 1
    assert res["context"]["shared_case_mix"] is True


def test_measurement_and_bias_items_track_artifacts():
    store = Store(":memory:")
    ids = [_seed(store, "gpt-x", 0.5, seed=1), _seed(store, "cl-z", 0.2, seed=1)]
    by = {i["n"]: i for i in strobe.checklist(store, ids)["items"]}
    assert by[8]["status"] == strobe.PARTIAL and by[9]["status"] == strobe.PARTIAL
    _adjudicate(store, ids[0], 30, 0.9, 0.9, seed=2)
    aid = store.create_grader_audit({"judges": ["mock:j"]})
    store.update_grader_audit(aid, status="complete")
    by = {i["n"]: i for i in strobe.checklist(store, ids)["items"]}
    assert by[8]["status"] == strobe.REPORTED and "clinician" in by[8]["where"]
    assert by[9]["status"] == strobe.REPORTED
    assert by[22]["status"] == strobe.NA


def test_single_run_main_results_partial():
    store = Store(":memory:")
    rid = _seed(store, "gpt-x", 0.5, seed=1)
    res = strobe.checklist(store, [rid])
    by = {i["n"]: i for i in res["items"]}
    assert by[16]["status"] == strobe.PARTIAL and "referent" in by[16]["where"]
    assert any(i["n"] == 16 for i in res["todo"])


def test_render_and_endpoints():
    store = Store(":memory:")
    settings = Settings(db_path=":memory:")
    app = create_app(settings, store, Runner(settings, store, mocks={}))
    ids = [_seed(store, "gpt-x", 0.5, seed=1), _seed(store, "cl-z", 0.2, seed=1)]
    c = TestClient(app)
    q = ",".join(ids)
    j = c.get(f"/strobe.json?runs={q}").json()
    assert j["score"]["applicable"] == 21
    html = c.get(f"/strobe?runs={q}").text
    assert "STROBE-style reporting checklist" in html and "Still to write" in html and "topnav" in html
    assert c.get("/strobe.json?runs=nope").status_code == 404
