import threading
import time

from app import crawler, fda
from app.config import Settings
from app.manager import CrawlManager
from app.store import Store
from tests.fakes import FakeClient, fake_refresh, response, text, tool_use

PLAN = {
    "summary": "MS lesion MRI",
    "conditions": [{"name": "multiple sclerosis", "display": "Multiple Sclerosis",
                    "synonyms": ["ms"], "fda_terms": ["white matter lesion"]}],
    "modalities": ["mri"],
    "angles": [{"focus": "challenges", "instructions": "MICCAI MS lesion challenges"},
               {"focus": "openneuro", "instructions": "OpenNeuro MS datasets"}],
}
RECORD = {
    "title": "MSSEG-2", "url": "https://portal.fli-iam.irisa.fr/msseg-2/", "source": "FLI-IAM",
    "description": "New MS lesion segmentation on FLAIR.", "conditions": ["Multiple Sclerosis"],
    "modalities": ["mri"], "labels": "lesion masks", "size": "", "n_subjects": "100",
    "file_formats": ["nii.gz"], "license": "", "access_type": "registration",
    "access_instructions": "Register on the FLI-IAM portal.", "download_urls": [],
    "citation": "", "tags": ["challenge"],
}


def ctx_for(tmp_path, minutes=5, **settings_kw):
    settings = Settings(data_dir=tmp_path, swarm_size=2, **settings_kw)
    store = Store(settings.db_path)
    cid = store.create_crawl("query", "MS brain MRI", minutes)
    seen = []
    ctx = crawler.CrawlContext(cid, store, settings, time.monotonic() + minutes * 60,
                               threading.Event(), lambda i, n: seen.append((i, n)))
    return ctx, seen


def test_agent_records_dataset_and_returns_tool_results(tmp_path, monkeypatch):
    monkeypatch.setattr(fda, "refresh_condition", fake_refresh(lambda n: 3))
    ctx, seen = ctx_for(tmp_path)
    client = FakeClient(PLAN, [
        response([text("found one"), tool_use("record_dataset", RECORD, "tu_a"),
                  tool_use("record_dataset", {"title": "bad", "url": "ftp://x"}, "tu_b")],
                 "tool_use"),
        response([text("summary")], "end_turn"),
    ])
    plan = crawler.run_swarm(client, ctx, "MS brain MRI with contrast and clinical labels")
    assert plan["summary"] == "MS lesion MRI"
    crawl = ctx.store.get_crawl(ctx.crawl_id)
    assert len(crawl["hits"]) == 1 and crawl["new_hits"] == crawl["hits"]
    assert seen == [(crawl["hits"][0], True)]
    assert ctx.store.get_condition("multiple sclerosis")["fda_510k_count"] == 3
    assert crawl["input_tokens"] > 0
    # The tool results went back in one user message, the bad record flagged.
    followup = next(c for c in client.calls if len(c["messages"]) == 3)
    results = [b for b in followup["messages"][2]["content"] if b.get("type") == "tool_result"]
    assert [r["is_error"] for r in results] == [False, True]
    # Defaults: adaptive thinking, fallbacks on.
    assert followup["thinking"] == {"type": "adaptive"}
    assert followup["fallbacks"] == "default" and followup["betas"] == [crawler.FALLBACK_BETA]


def test_agent_stops_at_deadline_and_on_cancel(tmp_path, monkeypatch):
    monkeypatch.setattr(fda, "refresh_condition", fake_refresh(lambda n: 0))
    ctx, _ = ctx_for(tmp_path)
    ctx.deadline = time.monotonic() - 1
    client = FakeClient(PLAN)
    assert crawler.run_agent(client, ctx, "task", "a1") == 0
    ctx.deadline = time.monotonic() + 60
    ctx.cancel.set()
    assert crawler.run_agent(client, ctx, "task", "a1") == 0


def test_pause_turn_resumes_and_refusal_stops(tmp_path):
    ctx, _ = ctx_for(tmp_path)
    client = FakeClient(PLAN, [response([text("...")], "pause_turn"),
                               response([], "refusal")])
    assert crawler.run_agent(client, ctx, "task", "a1") == 2
    assert "declined" in ctx.store.get_crawl(ctx.crawl_id)["log"][-1]["msg"]


def test_fallbacks_off(tmp_path):
    ctx, _ = ctx_for(tmp_path, fallbacks="off")
    client = FakeClient(PLAN)
    crawler.run_agent(client, ctx, "task", "a1")
    assert "fallbacks" not in client.calls[0] and "betas" not in client.calls[0]


def test_manager_runs_broad_crawl_in_510k_order(tmp_path, monkeypatch):
    counts = {"pneumothorax": 15, "stroke": 90}
    monkeypatch.setattr(fda, "refresh_condition",
                        fake_refresh(lambda n: counts.get(n.lower(), 0)))
    monkeypatch.setattr("app.manager.load_seed", lambda: [
        {"name": "pneumothorax", "fda_terms": []}, {"name": "stroke", "fda_terms": []}])
    settings = Settings(data_dir=tmp_path, swarm_size=1, download_enabled=False,
                        fda_recent_months=0)
    store = Store(settings.db_path)
    client = FakeClient(PLAN)
    mgr = CrawlManager(store, settings, client_factory=lambda s: client)
    cid = mgr.start("broad", minutes=1)
    mgr.wait(cid, timeout=10)
    c = store.get_crawl(cid)
    assert c["status"] == "done", c
    planned = [call["messages"][0]["content"] for call in client.calls
               if "format" in (call.get("output_config") or {})]
    assert "Stroke" in planned[0] and "Pneumothorax" in planned[1]


def test_planner_and_agents_use_their_own_models(tmp_path):
    ctx, _ = ctx_for(tmp_path, model="worker-model", planner_model="planner-model")
    client = FakeClient(PLAN)
    crawler.plan_crawl(client, ctx, "MS brain MRI", 2)
    crawler.run_agent(client, ctx, "task", "a1")
    assert client.calls[0]["model"] == "planner-model"
    assert all(c["model"] == "worker-model" for c in client.calls[1:])


def test_planner_model_falls_back_to_datasets_model(monkeypatch):
    import importlib
    from app import config
    monkeypatch.delenv("DATASETS_PLANNER_MODEL", raising=False)
    monkeypatch.setenv("DATASETS_MODEL", "only-model")
    try:
        s = importlib.reload(config).Settings()
        assert s.model == s.planner_model == "only-model"
        monkeypatch.delenv("DATASETS_MODEL")
        s = importlib.reload(config).Settings()
        assert (s.model, s.planner_model) == ("claude-sonnet-5-5", "claude-opus-5-5")
    finally:
        importlib.reload(config)


def test_broad_crawl_syncs_recent_fda_first(tmp_path, monkeypatch):
    from app import devices as devmod
    calls = []

    def fake_sync(store, settings, session=None, months=None):
        calls.append(1)
        out = {"at": "2099-01-01T00:00:00+00:00", "since": "2024-11-13", "stored": 6600,
               "software": 900, "newest": "2026-10-30"}
        store.kv_set(devmod.RECENT_KEY, __import__("json").dumps(out))
        return out

    monkeypatch.setattr(devmod, "sync_recent", fake_sync)
    monkeypatch.setattr(fda, "refresh_condition", fake_refresh(lambda n: 1))
    monkeypatch.setattr("app.manager.load_seed", lambda: [{"name": "stroke", "fda_terms": []}])
    settings = Settings(data_dir=tmp_path, swarm_size=1, download_enabled=False)
    store = Store(settings.db_path)
    mgr = CrawlManager(store, settings, client_factory=lambda s: FakeClient(PLAN))
    for _ in range(2):
        cid = mgr.start("broad", minutes=1)
        mgr.wait(cid, timeout=10)
    assert len(calls) == 1                     # second crawl: synced within 6 h, skipped
    msgs = [m["msg"] for m in store.get_crawl(cid)["log"]]
    assert any("already synced (6600 since 2024-11-13)" in m for m in msgs)
