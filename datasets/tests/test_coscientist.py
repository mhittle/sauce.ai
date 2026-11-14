import json
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

from app.coscientist import CoScientist, N_GENERATE
from app.explore import heuristic_spec
from tests.fakes import response, text
from tests.test_explore import _manager


def hyp(i):
    return {"title": f"H{i}", "statement": f"acc_x differs by activity ({i})", "rationale": "r",
            "evidence": [f"fall mean acc_x higher (n=6) #{i}"], "exposure": "activity",
            "outcome": "acc_x", "covariates": [], "test_plan": "t-test", "data_gaps": "",
            "literature": [{"citation": "Paper", "url": "https://doi.org/10.1/x"}]}


def review(selected):
    return {"reviews": [{"number": n, "feasibility": 4, "value": 3, "novelty": 2, "rigor": 4,
                         "critique": f"c{n}"} for n in range(1, N_GENERATE + 1)],
            "selected": [{"number": n, "why": f"w{n}"} for n in selected],
            "summary": "Five diverse, testable leads."}


class Client:
    """Compose for the build, then a generator and a reviewer agent."""

    def __init__(self, store_ds):
        self.m, self.ds = store_ds
        self.calls = []
        self.beta = NS(messages=NS(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        sysmsg = kw.get("system") or ""
        if "format" in (kw.get("output_config") or {}):   # explore compose
            return response([text(json.dumps(heuristic_spec(self.m.get(self.ds)["source"]["probe"])))], "end_turn")
        last = kw["messages"][-1]["content"]
        results = last if isinstance(last, list) else []
        if "skeptical senior reviewer" in sysmsg:
            if not results:
                return response([NS(type="tool_use", id="r1", name="describe_data", input={})], "tool_use")
            if any(r.get("is_error") for r in results) or results[0]["tool_use_id"] == "r1":
                if results[0]["tool_use_id"] == "r1":     # first try: only 4 selected -> rejected
                    return response([NS(type="tool_use", id="r2", name="submit_review",
                                        input=review([1, 2, 3, 4]))], "tool_use")
                return response([NS(type="tool_use", id="r3", name="submit_review",
                                    input=review([3, 1, 7, 9, 10]))], "tool_use")
            raise AssertionError("unexpected")
        # generator
        if not results:
            return response([NS(type="tool_use", id="g1", name="group_summary",
                                input={"fields": ["acc_x"], "group_by": "activity"})], "tool_use")
        if results[0]["tool_use_id"] == "g1":
            out = json.loads(results[0]["content"])
            assert out["rows"][0]["group"] == "fall"
            return response([text("Thinking about it.")], "end_turn")   # forgets to submit
        raise AssertionError("unexpected")


def test_generate_review_select(tmp_path):
    holder = {}
    m, store, ds = _manager(tmp_path, client_factory=lambda s: holder["c"])
    holder["c"] = Client((m, ds))
    m.build_blocking(ds)
    cs = CoScientist(m)
    calls = holder["c"].calls

    # Generator nudged to submit after ending its turn without doing so.
    orig = holder["c"].create

    def create(**kw):
        last = kw["messages"][-1]["content"]
        if isinstance(last, str) and last.startswith("Call submit_hypotheses"):
            calls.append(kw)
            return response([NS(type="tool_use", id="g2", name="submit_hypotheses",
                                input={"hypotheses": [hyp(i) for i in range(1, 11)]})], "tool_use")
        return orig(**kw)
    holder["c"].beta = NS(messages=NS(create=create))

    with store._write() as c:
        c.execute("INSERT INTO hypothesis_runs (dataset_id, status, started_at) VALUES (?, 'generating', 'x')", (ds,))
    run_id = cs.start(ds)
    cs._jobs[ds].join(30)
    out = cs.latest(ds)
    assert out["status"] == "ready", out.get("error")
    assert [h["number"] for h in out["selected"]] == [3, 1, 7, 9, 10]
    assert out["selected"][0]["rank"] == 1 and out["selected"][0]["why"] == "w3"
    assert out["selected"][0]["scores"] == {"feasibility": 4, "value": 3, "novelty": 2, "rigor": 4}
    assert len(out["candidates"]) == 10 and out["runs_ready"] == 1 and out["id"] == run_id
    assert any("group_summary" in line for line in out["log"])
    tools = [t.get("name") for t in calls[-1]["tools"]]
    assert {"submit_review", "publications", "web_search"} <= set(tools)
    # a stale "generating" row from before a restart is marked failed on startup
    CoScientist(m)
    with store._conn() as c:
        assert c.execute("SELECT status FROM hypothesis_runs WHERE started_at = 'x'").fetchone()[0] == "failed"


def test_validation():
    from app.coscientist import _validate_hypotheses, _validate_review
    assert "exactly 10" in _validate_hypotheses({"hypotheses": [hyp(1)] * 9})
    assert "distinct" in _validate_hypotheses({"hypotheses": [hyp(1)] * 10})
    assert _validate_hypotheses({"hypotheses": [hyp(i) for i in range(10)]}) is None
    assert "select exactly" in _validate_review(review([1, 1, 2, 3, 4]))
    bad = review([1, 2, 3, 4, 5]); bad["reviews"][0]["value"] = 9
    assert "1 to 5" in _validate_review(bad)
    assert _validate_review(review([1, 2, 3, 4, 5])) is None


def test_api_requires_token_and_built_page(tmp_path, monkeypatch):
    from app.config import Settings
    from app.main import create_app
    from app.store import Store
    settings = Settings(data_dir=tmp_path, edit_token="s3cret", anthropic_api_key="k",
                        literature_enabled=False, devices_enabled=False, compat_enabled=False)
    store = Store(settings.db_path)
    ds, _ = store.upsert_dataset({"title": "X", "url": "https://x.org", "access_type": "open"})
    client = TestClient(create_app(settings, store=store))
    assert client.get(f"/api/explore/{ds}/hypotheses").json() == {"status": "none"}
    assert client.post(f"/api/explore/{ds}/hypotheses").status_code == 401
    r = client.post(f"/api/explore/{ds}/hypotheses", headers={"X-Edit-Token": "s3cret"})
    assert r.status_code == 409 and "build the explore page" in r.json()["detail"]
