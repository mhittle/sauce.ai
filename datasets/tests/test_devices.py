import json
from types import SimpleNamespace as NS

import pytest

from app import devices as devmod
from app.config import Settings
from app.devices import (DeviceWorker, fetch_one, find_links, normalize_record,
                         summary_pdf_urls, sync_condition)
from app.store import Store
from tests.fakes import response, text


def rec(k, date, name="Pneumothorax triage", applicant="Acme"):
    return {"k_number": k, "device_name": name, "applicant": applicant, "decision_date": date,
            "date_received": "2021-01-01", "decision_description": "Substantially Equivalent",
            "product_code": "QFM", "openfda": {"device_name": "Radiological CAD", "device_class": "2",
                                               "registration_number": ["1"]}}


class Session:
    def __init__(self, pages=None, pdfs=None):
        self.pages, self.pdfs, self.urls = pages or [], pdfs or {}, []

    def get(self, url, **kw):
        self.urls.append(url)
        if "api.fda.gov" in url:
            if "k_number:" in url:
                k = url.split("k_number:")[1].split("&")[0]
                hits = [r for page in self.pages for r in page if r["k_number"] == k]
                return NS(status_code=200 if hits else 404, json=lambda: {"results": hits})
            skip = int(url.split("skip=")[1].split("&")[0])
            idx = skip // 2
            if not self.pages:
                return NS(status_code=404, json=lambda: {})
            total = sum(len(p) for p in self.pages)
            batch = self.pages[idx] if idx < len(self.pages) else []
            return NS(status_code=200, json=lambda: {"meta": {"results": {"total": total}},
                                                     "results": batch})
        body = self.pdfs.get(url)
        if body is None:
            return NS(status_code=404, headers={})
        return NS(status_code=200, headers={"Content-Type": "application/pdf"},
                  iter_content=lambda n: [body])


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(devmod, "PAGE", 2)
    settings = Settings(data_dir=tmp_path, device_interval_sec=0, openfda_api_key=None)
    store = Store(settings.db_path)
    store.upsert_condition("pneumothorax", fda_terms=["chest x-ray triage", "ms"])
    return settings, store


def test_record_and_urls():
    d = normalize_record(rec("DEN200001", "2021-05-01"))
    assert d["submission_type"] == "denovo" and d["generic_name"] == "Radiological CAD"
    assert "registration_number" not in d["raw"]
    assert summary_pdf_urls("K213941")[0].endswith("/pdf21/K213941.pdf")
    assert summary_pdf_urls("K991234") == ["https://www.accessdata.fda.gov/cdrh_docs/pdf/K991234.pdf"]
    assert summary_pdf_urls("DEN170073")[0].endswith("/reviews/DEN170073.pdf")


def test_sync_paginates_and_counts_denovo(env):
    settings, store = env
    sess = Session(pages=[[rec("K210001", "2022-01-01"), rec("DEN210002", "2021-06-01")],
                          [rec("K200003", "2020-01-01")]])
    out = sync_condition(store, "pneumothorax", settings, sess)
    assert out == {"n_510k": 2, "n_denovo": 1, "stored": 3, "total": 3}
    assert '"ms"' not in sess.urls[0] and "sort=decision_date:desc" in sess.urls[0]
    c = store.get_condition("pneumothorax")
    assert (c["fda_510k_count"], c["fda_denovo_count"]) == (2, 1)
    lst = store.list_devices("pneumothorax", sort="applicant", direction="asc")
    assert lst["total"] == 3
    assert [d["k_number"] for d in store.list_devices(submission_type="denovo")["items"]] == ["DEN210002"]
    assert store.list_devices(q="K2000")["total"] == 1
    ranked = store.conditions_ranked()[0]
    assert ranked["fda_denovo_count"] == 1


def test_sync_no_matches_is_zero(env):
    settings, store = env
    assert sync_condition(store, "pneumothorax", settings, Session())["n_510k"] == 0


def test_find_links_alias_title_doi(env):
    settings, store = env
    ds, _ = store.upsert_dataset({"title": "ChestX-ray14", "url": "https://nih.gov/cxr14",
                                  "conditions": ["pneumothorax"]})
    store.upsert_article({"id": "pmid:1", "title": "ChestX-ray8: Hospital-scale chest X-ray database"
                          " and benchmarks", "doi": "10.1109/cvpr.2017.369"})
    store.link_article(ds, "pmid:1", "descriptor", "doi")
    store.save_literature_state(ds, status="complete", aliases=["ChestX-ray14"],
                                descriptors=[{"article_id": "pmid:1", "title":
                                              "ChestX-ray8: Hospital-scale chest X-ray database"
                                              " and benchmarks"}])
    txt = ("Training used the NIH ChestX-ray14 dataset. See Wang X et al. ChestX-ray8: "
           "hospital-scale chest x-ray database and benchmarks. doi:10.1109/CVPR.2017.369")
    links = find_links(store, txt)
    vias = sorted(l["via"] for l in links)
    assert vias == ["alias", "doi"]  # title match merges into the doi link for the same paper
    assert all(l["dataset_id"] == ds for l in links)
    assert "ChestX-ray14 dataset" in next(l for l in links if l["via"] == "alias")["snippet"]
    assert find_links(store, "No public datasets were used; ChestX-ray140 is not it.") == []


def test_worker_reads_pdf_and_extracts_on_request(env, monkeypatch):
    settings, store = env
    sess = Session(pages=[[rec("K213941", "2022-02-24")]],
                   pdfs={summary_pdf_urls("K213941")[0]: b"%PDF-fake"})
    sync_condition(store, "pneumothorax", settings, sess)
    ds, _ = store.upsert_dataset({"title": "SIIM-ACR Pneumothorax", "url": "https://kaggle.com/siim",
                                  "conditions": ["pneumothorax"]})
    monkeypatch.setattr(devmod, "pdf_text", lambda data: (
        "Predicate K190424. Validated on the SIIM-ACR Pneumothorax data.", 3))

    class Client:
        calls = 0

        def __init__(self):
            self.beta = NS(messages=NS(create=self.create))

        def create(self, **kw):
            Client.calls += 1
            out = {k: "" for k in ("summary", "intended_use", "technology", "training_data",
                                   "reference_standard", "limitations")}
            out.update(summary="Triage of pneumothorax.", is_ai_ml=True, performance=[],
                       predicate_devices=["K190424"], datasets_named=["SIIM-ACR Pneumothorax"],
                       references=[], test_data={k: "" for k in
                                                 ("description", "n_cases", "n_sites",
                                                  "countries", "design")})
            return response([text(json.dumps(out))], "end_turn")

    w = DeviceWorker(store, settings, client_factory=lambda s: Client(), session=sess)
    store.request_device_analysis("K213941")
    assert w.step()                       # requested: fetch + extract in one go
    d = store.get_device("K213941")
    assert d["doc"]["status"] == "done" and d["doc"]["pages"] == 3
    assert d["doc"]["predicates"] == [{"k_number": "K190424", "known": False}]
    assert d["doc"]["extracted"]["summary"] == "Triage of pneumothorax."
    assert [l["dataset_id"] for l in d["links"]] == [ds]
    assert store.get_dataset(ds)["devices"][0]["k_number"] == "K213941"
    assert Client.calls == 1
    assert w.step() is False              # nothing left: background never calls the LLM
    assert Client.calls == 1


def test_fetch_one_predicate(env):
    settings, store = env
    sess = Session(pages=[[rec("K190424", "2019-06-01")]])
    assert fetch_one(store, "K190424", settings, sess) and store.get_device("K190424")
    assert not fetch_one(store, "K000000", settings, Session(pages=[[rec("K1", "x")]]))
    assert not fetch_one(store, "DROP TABLE", settings, sess)
