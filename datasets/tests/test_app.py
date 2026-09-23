import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.manager import CrawlManager  # noqa: E402
from app.store import Store  # noqa: E402
from tests.fakes import FakeClient  # noqa: E402
from tests.test_crawler import PLAN, RECORD  # noqa: E402


def make(tmp_path, llm=True):
    settings = Settings(data_dir=tmp_path, swarm_size=1, download_enabled=False)
    store = Store(settings.db_path)
    mgr = CrawlManager(store, settings, client_factory=(lambda s: FakeClient(PLAN))
                       if llm else None)
    return TestClient(create_app(settings, store, mgr)), store, mgr


def test_health_and_ui(tmp_path):
    client, _, _ = make(tmp_path, llm=False)
    assert client.get("/health").json()["llm_configured"] is False
    assert "sauce.ai" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200


def test_search_shows_indexed_and_condition_510k(tmp_path):
    client, store, _ = make(tmp_path, llm=False)
    store.upsert_dataset(RECORD)
    store.upsert_condition("multiple sclerosis", synonyms=["ms"])
    store.set_condition_510k("multiple sclerosis", 4)
    body = client.get("/api/search", params={"q": "MS brain MRI"}).json()
    assert [r["title"] for r in body["results"]] == ["MSSEG-2"]
    assert body["conditions"][0]["fda_510k_count"] == 4
    assert body["crawl_recommended"] is True


def test_crawl_requires_llm(tmp_path):
    client, _, _ = make(tmp_path, llm=False)
    r = client.post("/api/crawls", json={"mode": "query", "query": "pneumothorax"})
    assert r.status_code == 503


def test_query_crawl_then_memoized(tmp_path, monkeypatch):
    monkeypatch.setattr("app.fda.count_510k", lambda terms, **kw: 1)
    client, store, mgr = make(tmp_path)
    r = client.post("/api/crawls", json={"mode": "query", "query": "MS brain MRI"}).json()
    assert r["reused"] is False
    mgr.wait(r["crawl_id"], timeout=10)
    assert client.get(f"/api/crawls/{r['crawl_id']}").json()["status"] == "done"
    # Same query (reordered) within the recrawl window reuses the crawl...
    again = client.post("/api/crawls", json={"mode": "query", "query": "brain MRI ms"}).json()
    assert again == {"crawl_id": r["crawl_id"], "reused": True, "status": "done"}
    search = client.get("/api/search", params={"q": "brain mri MS"}).json()
    assert search["crawl_recommended"] is False
    # ...unless forced.
    forced = client.post("/api/crawls", json={"mode": "query", "query": "MS brain MRI",
                                              "force": True}).json()
    assert forced["reused"] is False
    mgr.wait(forced["crawl_id"], timeout=10)
    assert len(client.get("/api/crawls").json()) == 2


def test_directory_datasets_and_files(tmp_path):
    client, store, _ = make(tmp_path, llm=False)
    ds_id, _ = store.upsert_dataset(RECORD)
    rows = client.get("/api/conditions", params={"with_datasets": True}).json()
    assert rows[0]["name"] == "multiple sclerosis" and rows[0]["n_datasets"] == 1
    assert client.get("/api/datasets", params={"condition": "Multiple Sclerosis"}).json()[0]["id"] == ds_id
    assert client.get(f"/api/datasets/{ds_id}").json()["files"] == []
    assert client.get("/api/datasets/nope").status_code == 404
    # A file row pointing outside the files dir is never served.
    fid = store.record_file(ds_id, "https://x/a.csv", "downloaded", local_path="/etc/passwd",
                            filename="a.csv")
    assert client.get(f"/files/{fid}").status_code == 404
    good = tmp_path / "files" / ds_id / "a.csv"
    good.parent.mkdir(parents=True)
    good.write_text("a,b\n")
    fid = store.record_file(ds_id, "https://x/b.csv", "downloaded", local_path=str(good),
                            filename="a.csv")
    assert client.get(f"/files/{fid}").text == "a,b\n"
