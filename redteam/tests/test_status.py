"""Live worker status: every run in flight."""
import sys
import time

from fastapi.testclient import TestClient

from app import status
from app.config import Settings
from app.main import create_app
from app.runner import Runner
from app.store import Store


def test_snapshot_groups_runs_and_projects_pace():
    store = Store(":memory:")
    now = time.time()
    cfg = {"specialty": "cardiology", "super_run_id": "srx", "field_scan_id": "srx:cardiology"}
    tgt = {"kind": "openai_chat", "model": "gpt-5"}
    running = store.create_run("me@lab.edu", 20, cfg, tgt, 0.0)
    store.update_run(running, status="running", started_at=now - 600, completed_trials=10)
    queued = store.create_run("me@lab.edu", 20, {"specialty": "psychiatry"}, tgt, 0.0)
    done = store.create_run("me@lab.edu", 4, {"specialty": "oncology"}, tgt, 0.0)
    store.update_run(done, status="complete", started_at=now - 900, finished_at=now - 300, completed_trials=4)
    failed = store.create_run("me@lab.edu", 4, {"specialty": "oncology"}, tgt, 0.0)
    store.update_run(failed, status="failed", finished_at=now - 100, error="target HTTP 429: no credits")
    old = store.create_run("me@lab.edu", 4, {"specialty": "oncology"}, tgt, 0.0)
    store.update_run(old, status="complete", finished_at=now - 3 * 86400, completed_trials=4)
    snap = status.snapshot(store, Settings(db_path=":memory:", worker_threads=8, openai_api_key="k"), now=now)
    assert snap["counts"] == {"running": 1, "queued": 1, "complete_24h": 1, "failed_24h": 1}
    r = snap["running"][0]
    assert r["run_id"] == running and r["display"] == "ChatGPT (GPT-5)" and r["pct"] == 50
    assert abs(r["trials_per_min"] - 1.0) < 1e-9 and abs(r["eta_s"] - 600) < 1e-6
    assert r["email"] == "me***@lab.edu" and r["super_run_id"] == "srx"
    assert snap["queued"][0]["run_id"] == queued
    assert {x["run_id"] for x in snap["recent"]} == {done, failed}   # the 3-day-old run is outside the window
    assert snap["in_flight"]["trials_remaining"] == 10 + 20 and abs(snap["in_flight"]["eta_s"] - 1800) < 1e-6
    assert snap["worker"]["worker_threads"] == 8 and "openai" in snap["worker"]["providers"]
    html = status.render_html(snap)
    assert "Runs in flight" in html and "ChatGPT (GPT-5)" in html and "no credits" in html and 'content="15"' in html
    assert "me@lab.edu" not in html


def test_status_endpoints():
    store = Store(":memory:")
    s = Settings(db_path=":memory:")
    c = TestClient(create_app(s, store, Runner(s, store, mocks={})))
    assert c.get("/status").status_code == 200 and "nothing running" in c.get("/status").text
    j = c.get("/status.json").json()
    assert j["counts"]["running"] == 0 and j["in_flight"]["eta_s"] is None
