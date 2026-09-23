import json
from types import SimpleNamespace as NS

from app.config import Settings
from app.literature import (EPMC, Http, LiteratureWorker, build_streams, clean_aliases,
                            find_dois, from_openalex, heuristic_resolve)
from app.store import Store
from tests.fakes import response, text

DS = {"title": "MSSEG-2 (MICCAI 2021) new MS lesions", "url": "https://portal.fli-iam.irisa.fr/msseg-2/",
      "description": "FLAIR MRI.", "citation": "Commowick O et al. doi:10.1038/S41598-018-31911-7.",
      "conditions": ["multiple sclerosis"], "access_type": "registration"}

DESCRIPTOR = {"id": "30250199", "source": "MED", "pmid": "30250199", "doi": "10.1038/s41598-018-31911-7",
              "title": "Objective evaluation of MS lesion segmentation: the MSSEG challenge dataset",
              "pubYear": "2018", "citedByCount": 300}


def epmc_hit(i, cited, **kw):
    return {"id": str(i), "source": "MED", "pmid": str(i), "title": f"Paper {i}",
            "pubYear": "2022", "citedByCount": cited, **kw}


class FakeSession:
    """Routes Europe PMC URLs to canned bodies; records calls."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, params=None, **kw):
        self.calls.append((url, dict(params or {})))
        for match, body in self.routes:
            if match(url, params or {}):
                status, payload = body if isinstance(body, tuple) else (200, body)
                return NS(status_code=status, json=lambda p=payload: p, text=json.dumps(payload))
        return NS(status_code=404, json=lambda: {}, text="")


def routes(cites_pages=1, fail_cites=False):
    def is_search(q):
        return lambda u, p: u == f"{EPMC}/search" and q(p.get("query", ""))
    cite_body = (503, {}) if fail_cites else {
        "hitCount": 3, "citationList": {"citation": [epmc_hit(1, 50), epmc_hit(2, 900),
                                                     epmc_hit(30250199, 300)]}}
    return [
        (is_search(lambda q: q.startswith("DOI:")), {"resultList": {"result": [DESCRIPTOR]}}),
        (is_search(lambda q: q == '"MSSEG-2"'), {"hitCount": 2, "nextCursorMark": "x",
                                                 "resultList": {"result": [epmc_hit(2, 900),
                                                                           epmc_hit(3, 5)]}}),
        (is_search(lambda q: True), {"resultList": {"result": []}}),
        (lambda u, p: u.endswith("/MED/30250199/citations"), cite_body),
    ]


def worker(tmp_path, session, client_factory=None):
    settings = Settings(data_dir=tmp_path, openalex_api_key=None, lit_interval_sec=0)
    store = Store(settings.db_path)
    ds_id, _ = store.upsert_dataset(DS)
    w = LiteratureWorker(store, settings, client_factory=client_factory,
                         http=Http(settings, session=session, sleep=lambda s: None))
    return w, store, ds_id


def test_find_dois_and_openalex_record():
    assert find_dois("see https://doi.org/10.1000/ABC.1. and zenodo.org/records/42") == \
        ["10.1000/abc.1", "10.5281/zenodo.42"]
    art = from_openalex({"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1/X",
                         "ids": {"pmid": "https://pubmed.ncbi.nlm.nih.gov/99"},
                         "display_name": "T", "cited_by_count": 7, "publication_year": 2020,
                         "authorships": [{"author": {"display_name": "A B"}}]})
    assert art["id"] == "pmid:99" and art["doi"] == "10.1/x" and art["openalex_id"] == "W1"


def test_heuristic_skips_generic_acronyms():
    out = heuristic_resolve(DS, [])
    assert "MICCAI" not in out["aliases"] and "MSSEG-2" in out["aliases"]
    assert clean_aliases(["MRI", "ct", "BraTS 2021", "BraTS 2021"]) == ["BraTS 2021"]
    kinds = [s["kind"] for s in build_streams([{"epmc": "MED:1", "openalex_id": "W1"}],
                                              ["X-Set"], openalex=False)]
    assert kinds == ["epmc_cites", "epmc_mentions"]


def test_full_cycle_cites_first_then_mentions(tmp_path):
    w, store, ds_id = worker(tmp_path, FakeSession(routes()))
    w.step()                                    # resolve (heuristic: DOI match)
    st = store.literature_state(ds_id)
    assert [d["title"] for d in st["descriptors"]] == [DESCRIPTOR["title"]]
    assert st["streams"][0]["kind"] == "epmc_cites"
    w.step()                                    # cites page
    w.step()                                    # mentions page
    assert store.literature_state(ds_id)["status"] == "complete"
    res = store.dataset_articles(ds_id)
    # descriptor first, then citers by citation count, then mention-only.
    assert [a["pmid"] for a in res["items"]] == ["30250199", "2", "1", "3"]
    assert res["items"][1]["cites"] == 1 and res["items"][1]["mentions"] == 1
    assert (res["total"], res["cites"], res["mentions_only"]) == (3, 2, 1)
    assert store.get_dataset(ds_id)["n_articles"] == 3
    assert w.step() is False                    # nothing due


def test_transient_errors_retry_then_give_up(tmp_path):
    w, store, ds_id = worker(tmp_path, FakeSession(routes(fail_cites=True)))
    w.step()
    for _ in range(5):
        w.step()
    st = store.literature_state(ds_id)
    cites = st["streams"][0]
    assert cites["done"] and cites["failures"] == 5 and "503" in cites["error"]


def test_llm_resolution_filters_ids(tmp_path):
    class Client:
        def __init__(self):
            self.beta = NS(messages=NS(create=self.create))

        def create(self, **kw):
            assert kw["output_config"]["format"]["type"] == "json_schema"
            return response([text(json.dumps({
                "descriptor_ids": ["pmid:30250199", "pmid:bogus"],
                "extra_descriptor_dois": [], "aliases": ["MSSEG-2", "MRI"],
                "note": "confident"}))], "end_turn")

    w, store, ds_id = worker(tmp_path, FakeSession(routes()), client_factory=lambda s: Client())
    w.step()
    st = store.literature_state(ds_id)
    assert [d["article_id"] for d in st["descriptors"]] == ["pmid:30250199"]
    assert st["aliases"] == ["MSSEG-2"] and st["note"] == "confident"


def test_refresh_resets_cursors(tmp_path):
    w, store, ds_id = worker(tmp_path, FakeSession(routes()))
    for _ in range(3):
        w.step()
    store.save_literature_state(ds_id, completed_at="2000-01-01T00:00:00+00:00")
    with store._write() as c:
        c.execute("UPDATE literature_state SET last_worked = '2000-01-01'")
    w.step()
    st = store.literature_state(ds_id)
    assert st["status"] == "active" and all(not s["done"] for s in st["streams"])
