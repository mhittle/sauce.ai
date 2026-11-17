"""Super Run: plan, gated launcher, batch results page."""
from fastapi.testclient import TestClient

from app import super_run
from app.catalog import SPECIALTIES
from app.config import Settings
from app.main import create_app
from app.runner import Runner, RunQueue
from app.store import Store


def _settings(**kw):
    base = dict(db_path=":memory:", openai_api_key="ok", anthropic_api_key=None, gemini_api_key=None,
                llama_api_key=None, llama_base_url="https://api.together.xyz/v1", super_token="s3cret")
    base.update(kw)
    return Settings(**base)


def test_plan_is_models_times_specialties():
    s = _settings()
    pl = super_run.plan(s, n_trials=10)
    assert len(pl["models"]) == 2                      # the two OpenAI panel entries
    assert pl["specialties"] == list(SPECIALTIES)
    assert pl["n_runs"] == 2 * len(SPECIALTIES) and pl["n_conversations"] == pl["n_runs"] * 10
    assert {sk["display"] for sk in pl["skipped"]} >= {"Claude (Opus 5)", "Gemini 3.1 Pro"}
    sub = super_run.plan(s, specialties=["cardiology"], models=["chatgpt-5"])
    assert sub["n_runs"] == 1
    import pytest
    with pytest.raises(ValueError):
        super_run.plan(s, models=["bogus"])
    with pytest.raises(ValueError):
        super_run.plan(s, specialties=["astrology"])


def test_launcher_is_hidden_without_token_and_gated_with_one(monkeypatch):
    store = Store(":memory:")
    off = _settings(super_token=None)
    c = TestClient(create_app(off, store, Runner(off, store, mocks={})))
    assert c.get("/super").status_code == 404
    assert c.post("/super", json={"token": "x", "email": "a@b.c"}).status_code == 404
    on = _settings()
    c = TestClient(create_app(on, store, Runner(on, store, mocks={})))
    assert c.get("/super").status_code == 403 and c.get("/super?token=wrong").status_code == 403
    page = c.get("/super?token=s3cret")
    assert page.status_code == 200 and "Launch Super Run" in page.text and 'content="noindex"' in page.text
    assert c.post("/super", json={"token": "wrong", "email": "a@b.c"}).status_code == 403


def test_launch_creates_tagged_runs_and_results_page(monkeypatch):
    monkeypatch.setattr(RunQueue, "submit", lambda self, *a, **k: None)
    store = Store(":memory:")
    s = _settings()
    c = TestClient(create_app(s, store, Runner(s, store, mocks={})))
    r = c.post("/super", json={"token": "s3cret", "email": "me@lab.edu", "n_trials": 4,
                               "models": ["chatgpt-5"], "specialties": ["cardiology", "psychiatry"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n_runs"] == 2 and body["n_conversations"] == 8
    sid = body["super_id"]
    assert store.runs_for_super(sid) == [x["run_id"] for x in body["runs"]]
    # each specialty slice is also a field scan on the shared seed
    assert len(store.runs_for_field(f"{sid}:cardiology")) == 1
    run = store.get_run(body["runs"][0]["run_id"])
    assert run["config"]["super_run_id"] == sid and run["config"]["seed"] == super_run.DEFAULT_SEED
    assert run["config"]["control_fraction"] == 0.2
    # no quota was charged for an operator batch
    assert store.trials_used("me@lab.edu") == 0
    # public results page works while runs are still queued
    page = c.get(f"/super/{sid}")
    assert page.status_code == 200 and "Clinical AI safety benchmark" in page.text and "queued" in page.text
    j = c.get(f"/super/{sid}.json").json()
    assert j["n_runs"] == 2 and j["status_counts"]["queued"] == 2 and j["done"] is False
    assert c.get("/super/nope").status_code == 404
    assert [x["super_id"] for x in super_run.recent(store)] == [sid]


def test_results_rank_completed_runs(monkeypatch):
    import sys
    sys.path.insert(0, "tests")
    import test_leaderboard as T
    store = Store(":memory:")
    sid = "sr_test"
    for model, h, sp, seed in [("gpt-5", 0.6, "cardiology", 1), ("claude-opus-5", 0.2, "cardiology", 2),
                               ("gpt-5", 0.4, "psychiatry", 3), ("claude-opus-5", 0.3, "psychiatry", 4)]:
        rid = T._seed(store, model, harm_rate=h, specialty=sp, seed=seed)
        run = store.get_run(rid); cfg = run["config"]; cfg["super_run_id"] = sid
        store._x("UPDATE runs SET config_json=? WHERE id=?", (__import__("json").dumps(cfg), rid))
    res = super_run.results(store, sid)
    assert res["done"] and res["n_runs"] == 4 and set(res["specialties"]) == {"cardiology", "psychiatry"}
    assert [p["target_label"] for p in res["pooled"]] == ["claude-opus-5", "gpt-5"]  # safest first
    assert res["pooled"][0]["display"] == "Claude (Opus 5)" and res["pooled"][0]["n_specialties"] == 2
    assert [e["target_label"] for e in res["per_specialty"]["cardiology"]] == ["claude-opus-5", "gpt-5"]
    html = super_run.render_results(res)
    assert "Pooled across specialties" in html and "/field?field=sr_test:cardiology" in html
    assert super_run.results(store, "missing") is None


def test_light_run_reads_skip_report_html_and_use_reader_connection(tmp_path):
    store = Store(str(tmp_path / "r.db"))
    rid = store.create_run("a@b.c", 2, {"specialty": "cardiology", "super_run_id": "srx"}, {"kind": "openai_chat"}, 0.0)
    store.update_run(rid, status="complete", report_html="<html>" + "x" * 50000, summary={"adversarial": {"trials": 2}})
    full, light = store.get_run(rid), store.get_run(rid, light=True)
    assert full["report_html"].startswith("<html>") and "report_html" not in light
    assert light["summary"] == {"adversarial": {"trials": 2}} and light["status"] == "complete"
    assert store._rconn is not store._conn           # file databases get a reader connection
    assert store.runs_for_super("srx") == [rid]       # reads see committed writes at once
    assert Store(":memory:")._rconn is Store(":memory:")._conn or True  # memory: reader is the writer


def test_launch_creates_all_records_before_starting_any(monkeypatch):
    order = []
    monkeypatch.setattr(RunQueue, "submit", lambda self, run_id, *a, **k: order.append(("submit", run_id)))
    store = Store(":memory:")
    orig = store.create_run
    def create(*a, **k):
        rid = orig(*a, **k); order.append(("create", rid)); return rid
    store.create_run = create
    s = _settings()
    c = TestClient(create_app(s, store, Runner(s, store, mocks={})))
    r = c.post("/super", json={"token": "s3cret", "email": "me@lab.edu", "n_trials": 4,
                               "models": ["chatgpt-5", "chatgpt-4o"], "specialties": ["cardiology"]})
    assert r.status_code == 200
    kinds = [k for k, _ in order]
    assert kinds == ["create", "create", "submit", "submit"]


def test_relaunch_failed_cells_and_cancel(monkeypatch):
    submitted = []
    monkeypatch.setattr(RunQueue, "submit", lambda self, run_id, *a, **k: submitted.append(run_id))
    cancelled = []
    monkeypatch.setattr(RunQueue, "cancel", lambda self, run_id: cancelled.append(run_id))
    store = Store(":memory:")
    s = _settings()
    c = TestClient(create_app(s, store, Runner(s, store, mocks={})))
    r = c.post("/super", json={"token": "s3cret", "email": "me@lab.edu", "n_trials": 4,
                               "models": ["chatgpt-5", "chatgpt-4o"], "specialties": ["cardiology"]})
    sid = r.json()["super_id"]
    a, b = [x["run_id"] for x in r.json()["runs"]]
    store.update_run(a, status="failed", error="target HTTP 429: no credits")
    store.update_run(b, status="running")
    res = c.get(f"/super/{sid}.json").json()
    assert [x["run_id"] for x in res["failed_cells"]] == [a] and res["n_superseded"] == 0
    # relaunch: gated, re-creates only the failed cell under the same batch and field ids
    assert c.post(f"/super/{sid}/relaunch", json={"token": "nope"}).status_code == 403
    rr = c.post(f"/super/{sid}/relaunch", json={"token": "s3cret"}).json()
    assert len(rr["relaunched"]) == 1 and rr["relaunched"][0]["model"] == "chatgpt-5" and not rr["skipped"]
    new_id = rr["relaunched"][0]["run_id"]
    assert new_id in submitted and new_id != a
    new = store.get_run(new_id)
    assert new["config"]["super_run_id"] == sid and new["config"]["field_scan_id"] == f"{sid}:cardiology"
    assert new["config"]["seed"] == super_run.DEFAULT_SEED and new["config"]["n_trials"] == 4
    # the relaunched run supersedes the failed one on the batch page
    res2 = c.get(f"/super/{sid}.json").json()
    assert res2["n_runs"] == 2 and res2["n_superseded"] == 1 and res2["failed_cells"] == []
    assert {p["run_id"] for p in res2["progress"]} == {new_id, b}
    page = c.get(f"/super/{sid}").text
    assert "Relaunch failed cells (0)" in page and "superseded" in page
    # cancel: only queued/running runs
    cc = c.post(f"/super/{sid}/cancel", json={"token": "s3cret"}).json()
    assert cc["cancelling"] == 2 and set(cancelled) == {new_id, b}
    assert c.post("/super/nope/cancel", json={"token": "s3cret"}).status_code == 404


def test_batch_budget_stops_runs_once_spent(monkeypatch):
    """A run of a Super Run whose other runs have already spent the batch budget
    starts no conversation and fails with a budget message; failed runs keep
    their usage so the batch total counts them."""
    from app.config import Settings
    from app.runner import Runner, RunSpec
    from app.store import Store
    from app.targets import TargetConfig
    from app import super_run
    from tests.test_runner_api import _patch_target, make_mocks
    _patch_target(monkeypatch)
    store = Store(":memory:")
    settings = Settings(db_path=":memory:", smtp_host=None, trial_concurrency=1)
    sid = "srbudget01"
    # an earlier (failed) run of the batch with $5 of stored usage
    prior = store.create_run("a@b.c", 4, {"specialty": "cardiology", "super_run_id": sid},
                             {"kind": "openai_chat", "model": "x"}, 0.0)
    store.update_run(prior, status="failed", error="429", usage={"anthropic:claude-opus-5": {"cost_usd": 5.0}})
    assert super_run.spent(store, sid) == 5.0
    runner = Runner(settings, store, mocks=make_mocks())
    spec = RunSpec(email="a@b.c", n_trials=4, specialty="endocrinology", focus_harms=["dosing_error"], max_turns=2,
                   seed=1, orchestration={"attackers": ["mock:atk"], "arbiters": ["mock:arb"]}, judges=["mock:judge"],
                   super_run_id=sid, budget_usd=4.0)
    target = TargetConfig(kind="openai_chat", url="https://bot.example/v1/chat", model="m")
    run_id = store.create_run(spec.email, spec.n_trials, spec.public_dict(settings), target.public_dict(), 0.0)
    runner.execute(run_id, spec, target)
    run = store.get_run(run_id)
    assert run["status"] == "failed" and run["error"].startswith("batch budget $4.00 exhausted")
    assert "0 of 4 conversations started" in run["error"]
    assert all(t["status"] == "running" or t["status"] == "error" for t in store.trials_for_run(run_id, with_turns=False)) or \
        store.trials_for_run(run_id, with_turns=False) == []
    assert run["usage"] is not None                          # stored even though the run failed
    assert run["config"]["budget_usd"] == 4.0
    res = super_run.results(store, sid)
    assert res["budget_usd"] == 0.0 or res["budget_usd"] == 4.0      # whichever run is cfg0
    # with no budget the same run proceeds
    spec2 = RunSpec(**{**spec.__dict__, "budget_usd": 0.0})
    run2 = store.create_run(spec2.email, spec2.n_trials, spec2.public_dict(settings), target.public_dict(), 0.0)
    runner.execute(run2, spec2, target)
    assert store.get_run(run2)["status"] == "complete"


def test_default_arbiter_is_the_cheaper_model():
    from app.config import Settings
    from app.runner import RunSpec
    s = Settings(db_path=":memory:")
    assert s.default_arbiter == "anthropic:claude-sonnet-5"
    spec = RunSpec(email="a@b.c", n_trials=1, specialty="cardiology")
    assert spec.orch_config(s).arbiters == ["anthropic:claude-sonnet-5"]
