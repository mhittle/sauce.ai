"""Target trial emulation: protocol rows, ITT vs per-protocol estimands,
shared case-mix check, DAG inclusion, report + endpoints."""
import sys
import xml.dom.minidom as minidom

from fastapi.testclient import TestClient

sys.path.insert(0, "tests")
from test_epi import _seed  # noqa: E402

from app import target_trial as tt  # noqa: E402
from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.runner import Runner  # noqa: E402
from app.store import Store  # noqa: E402


def _degrade_one(store, run_id):
    """Mark the first turn of the first conversation as degraded (protocol deviation)."""
    t = store.trials_for_run(run_id)[0]
    tid = t["turns"][0]["id"]
    with store._lock:
        store._conn.execute("UPDATE turns SET degraded=1 WHERE id=?", (tid,))
        store._conn.commit()


def test_emulation_builds_protocol_and_estimands():
    store = Store(":memory:")
    r_bad = _seed(store, "gpt-x", 0.6, seed=1)
    r_safe = _seed(store, "cl-z", 0.1, seed=1)
    res = tt.emulate(store, [r_bad, r_safe])
    assert res["n_agents"] == 2 and res["referent"]["run_id"] == r_safe
    assert res["shared_case_mix"] is True
    comps = [r["component"] for r in res["protocol"]]
    assert comps[0] == "Eligibility criteria" and "Causal contrasts of interest" in comps
    assert all(r["fidelity"] in ("matched", "approximated", "deviates") for r in res["protocol"])
    worst = res["agents"][0]
    assert worst["run_id"] == r_bad and worst["contrast"]["itt"]["risk_ratio"]["value"] > 1
    assert worst["per_protocol"]["n"] == worst["itt"]["n"]  # nothing degraded
    assert res["dag"]["trial"]["minimal_adjustment_sets"] == [[]]
    assert res["dag"]["observational"]["identifiable_by_adjustment"] is False
    assert len(res["threats"]) >= 6


def test_per_protocol_excludes_degraded_conversations():
    store = Store(":memory:")
    r_bad = _seed(store, "gpt-x", 0.6, seed=1)
    r_safe = _seed(store, "cl-z", 0.1, seed=1)
    _degrade_one(store, r_bad)
    res = tt.emulate(store, [r_bad, r_safe])
    bad = next(a for a in res["agents"] if a["run_id"] == r_bad)
    assert bad["per_protocol"]["excluded_degraded"] == 1
    assert bad["per_protocol"]["n"] == bad["itt"]["n"] - 1


def test_shared_case_mix_flag_false_when_seeds_differ():
    store = Store(":memory:")
    ids = [_seed(store, "gpt-x", 0.6, seed=1), _seed(store, "cl-z", 0.1, seed=2)]
    assert tt.emulate(store, ids)["shared_case_mix"] is False


def test_render_html_and_empty_case():
    store = Store(":memory:")
    ids = [_seed(store, "gpt-x", 0.6, seed=1), _seed(store, "cl-z", 0.1, seed=1)]
    html = tt.render_html(tt.emulate(store, ids))
    assert "Target trial emulation" in html and "Per-protocol" in html and "Minimal adjustment sets" in html
    assert html.count("<svg") == 2
    assert "No completed" in tt.render_html({"agents": [], "n_agents": 0})


def test_target_trial_endpoints():
    store = Store(":memory:")
    settings = Settings(db_path=":memory:")
    app = create_app(settings, store, Runner(settings, store, mocks={}))
    ids = [_seed(store, "gpt-x", 0.6, seed=1), _seed(store, "cl-z", 0.1, seed=1)]
    c = TestClient(app)
    q = ",".join(ids)
    j = c.get(f"/target-trial.json?runs={q}").json()
    assert j["n_agents"] == 2 and j["referent"]["run_id"] == ids[1]
    assert "Protocol" in c.get(f"/target-trial?runs={q}").text
    for d in ("trial", "observational"):
        r = c.get(f"/target-trial.svg?design={d}")
        assert r.headers["content-type"].startswith("image/svg+xml")
        minidom.parseString(r.text)
    assert c.get("/target-trial.svg?design=bogus").status_code == 400
    assert c.get(f"/target-trial.json?runs={q}&ref=nope").status_code == 400
