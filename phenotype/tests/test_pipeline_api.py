"""End-to-end: fake literature APIs + mock models through the pipeline and HTTP API."""
import time

from fastapi.testclient import TestClient

from app.literature import Literature
from app.main import create_app
from app.pipeline import JobSpec, Runner
from app.store import Store
from tests.fakes import fake_http, make_mocks, make_settings


def make_runner(**kw):
    settings = make_settings(**kw)
    store = Store(":memory:")
    lit = Literature(settings, http_get=fake_http, cache=store)
    return Runner(settings, store, literature=lit, mocks=make_mocks()), store


def run_job(**spec_kw):
    runner, store = make_runner()
    spec = JobSpec(condition="multiple sclerosis", expected_prevalence=0.003, country="United States", **spec_kw)
    spec.validate(runner.settings)
    job_id = store.create_job("", {})
    runner.execute(job_id, spec)
    return store.get_job(job_id)


def test_full_pipeline():
    job = run_job()
    assert job["status"] == "complete", job["error"]
    res = job["result"]
    flow = res["flow"]
    assert flow["identified"]["pubmed"] == 3 and flow["identified"]["europepmc"] == 1
    assert flow["identified"]["known_titles"] == {"suggested": 2, "resolved_in_pubmed": 1}  # fabricated dropped
    assert flow["identified"]["snowball"] == 1          # 555 via the citation graph
    assert flow["included"] == 3 and flow["extracted"] == 3

    top = res["candidates"][0]
    assert top["algorithm"]["name"] == ">=3 MS-related claims within 1 year"
    assert len(top["validations"]) == 3
    assert {v["dataset"] for v in top["validations"]} == {"VA", "Manitoba", "Medicare 5%"}
    assert top["pooled"]["sensitivity"]["k"] == 2 and top["pooled"]["ppv"]["k"] == 2
    assert top["at_prevalence"]["ppv"] is not None
    assert "COUNT(DISTINCT b.event_date) >= 3" in top["omop_sql"]
    assert ">= 3 qualifying events" in top["pseudocode"]
    assert any(v["url"] == "https://pubmed.ncbi.nlm.nih.gov/111/" for v in top["validations"])

    read = {s["key"]: s for s in res["studies"]}
    assert read["pmid:111"]["text_basis"] == "full text" and read["pmid:111"]["seed"]
    assert read["pmid:111"]["cited_by"] == 250
    assert {x["label"] for x in res["excluded"]} == {"exclude", "review"}

    # every study read links to the ranked algorithm(s) it develops or validates
    assert read["pmid:111"]["algorithms"] == [{"rank": 1, "name": top["algorithm"]["name"], "role": "developed"}]
    assert [(x["rank"], x["role"]) for x in read["pmid:222"]["algorithms"]] == [(1, "validated_existing"),
                                                                                (2, "developed")]
    assert {st["key"] for st in top["studies"]} == {"pmid:111", "pmid:222", "pmid:555"}

    html = job["report_html"]
    assert "Validated phenotyping algorithms for multiple sclerosis" in html
    assert "https://pubmed.ncbi.nlm.nih.gov/111/" in html and "<script" not in html
    assert "Rogan" in html
    assert 'id="alg-1"' in html and 'id="alg-2"' in html
    studies_html = html.split("<h2>Studies read</h2>")[1].split("</ol>")[0]
    assert studies_html.count('href="#alg-1"') == 3 and studies_html.count('href="#alg-2"') == 1
    assert "(develops)" in studies_html and "(validates)" in studies_html


def test_literature_outage_fails_cleanly():
    runner, store = make_runner()

    def down(url, params):
        raise RuntimeError("boom")
    runner.lit.http_get = down
    spec = JobSpec(condition="multiple sclerosis", model_suggestions=False)
    spec.validate(runner.settings)
    job_id = store.create_job("", {})
    runner.execute(job_id, spec)
    job = store.get_job(job_id)
    assert job["status"] == "failed" and "returned nothing" in job["error"]


def test_spec_validation():
    s = make_settings()
    for bad in (dict(condition="x"), dict(condition="asthma", intended_use="nope"),
                dict(condition="asthma", expected_prevalence=3), dict(condition="asthma", max_records=5),
                dict(condition="asthma", email="nope")):
        spec = JobSpec(**bad)
        try:
            spec.validate(s)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad}")


def test_http_api_roundtrip():
    runner, store = make_runner()
    client = TestClient(create_app(runner.settings, store, runner))
    assert client.get("/health").json() == {"ok": True}
    cfg = client.get("/config").json()
    assert "prevalence" in cfg["intended_uses"] and "claims" in cfg["data_types"]
    assert client.post("/jobs", json={"condition": "x"}).status_code == 400
    r = client.post("/jobs", json={"condition": "multiple sclerosis", "intended_use": "cohort"})
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    assert r.json()["poll"] == f"jobs/{job_id}/status"
    for _ in range(100):
        st = client.get(f"/jobs/{job_id}/status").json()
        if st["status"] in ("complete", "failed"):
            break
        time.sleep(0.05)
    assert st["status"] == "complete", st
    assert st["top"]["name"] == ">=3 MS-related claims within 1 year"
    assert "Ranking" in client.get(f"/jobs/{job_id}").text
    assert client.get(f"/jobs/{job_id}/export").json()["result"]["condition"] == "multiple sclerosis"
    sql = client.get(f"/jobs/{job_id}/algorithms/1.sql")
    assert sql.status_code == 200 and sql.text.startswith("-- sauce.ai/phenotype")
    assert client.get(f"/jobs/{job_id}/algorithms/99.sql").status_code == 404
    assert client.get("/jobs/nope/status").status_code == 404
    assert "phenotype" in client.get("/").text


def test_rate_limit():
    runner, store = make_runner(jobs_per_hour_per_ip=1)
    client = TestClient(create_app(runner.settings, store, runner))
    assert client.post("/jobs", json={"condition": "asthma"}).status_code == 200
    assert client.post("/jobs", json={"condition": "asthma"}).status_code == 429
