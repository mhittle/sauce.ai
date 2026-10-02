"""Table 1: case-mix by agent with standardized mean differences."""
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, "tests")
from test_epi import _seed  # noqa: E402

from app import table1  # noqa: E402
from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.runner import Runner  # noqa: E402
from app.store import Store  # noqa: E402


def test_smd_binary_matches_textbook_and_zero_when_identical():
    a = {"yes": 30, "no": 70}
    b = {"yes": 50, "no": 50}
    # binary SMD = (p1 - p2) / sqrt((p1(1-p1) + p2(1-p2)) / 2) = 0.2 / sqrt((0.21 + 0.25)/2)
    expect = 0.2 / ((0.21 + 0.25) / 2) ** 0.5
    assert abs(table1.smd_categorical(b, a) - expect) < 1e-9
    assert table1.smd_categorical(a, a) == 0.0
    assert table1.smd_categorical({"x": 10}, {"x": 10}) == 0.0  # single level
    assert table1.smd_categorical({}, a) is None


def test_shared_seed_runs_are_balanced():
    store = Store(":memory:")
    ids = [_seed(store, "gpt-x", 0.5, seed=3, n=60), _seed(store, "cl-z", 0.2, seed=3, n=60)]
    res = table1.table1(store, ids)
    assert res["n_runs"] == 2 and res["shared_case_mix"] is True
    assert res["balanced"] is True and res["max_smd"] == 0.0
    assert {r["covariate"] for r in res["rows"]} >= {"age_band", "sex", "health_literacy", "meds", "red_flag"}
    assert res["referent"]["run_id"] == ids[0]
    assert res["rows"][0]["smd"][0] is None and res["rows"][0]["smd"][1] == 0.0


def test_different_seeds_show_nonzero_smd_and_ref_param():
    store = Store(":memory:")
    ids = [_seed(store, "gpt-x", 0.5, seed=1, n=30), _seed(store, "cl-z", 0.2, seed=9, n=30)]
    res = table1.table1(store, ids, ref=ids[1])
    assert res["shared_case_mix"] is False and res["referent"]["run_id"] == ids[1]
    assert res["max_smd"] > 0
    assert res["rows"][0]["smd"][1] is None  # referent column


def test_render_and_endpoints():
    store = Store(":memory:")
    settings = Settings(db_path=":memory:")
    app = create_app(settings, store, Runner(settings, store, mocks={}))
    ids = [_seed(store, "gpt-x", 0.5, seed=3, n=40), _seed(store, "cl-z", 0.2, seed=3, n=40)]
    c = TestClient(app)
    q = ",".join(ids)
    j = c.get(f"/table1.json?runs={q}").json()
    assert j["balanced"] is True and len(j["columns"]) == 2
    html = c.get(f"/table1?runs={q}").text
    assert "Table 1" in html and "Balanced" in html and "Health literacy" in html and "topnav" in html
    assert c.get(f"/table1.json?runs={q}&ref=nope").status_code == 400
