import json
from types import SimpleNamespace as NS

from app.config import Settings
from app.importers import (OPENNEURO_API, PHYSIONET_API, TCIA_API, ImportRunner,
                           categorize_heuristic)
from app.store import Store
from tests.fakes import response, text

PHYSIONET = [
    {"slug": "mitdb", "version": "1.0.0", "is_latest_version": True, "resource_type": "Database",
     "title": "MIT-BIH Arrhythmia Database", "short_description": "48 half-hour ECG recordings.",
     "abstract": "<p>Two-channel <b>ambulatory ECG</b> with beat annotations.</p>",
     "license": {"name": "ODC-By 1.0"}, "access_policy": "Open", "core_doi": "10.13026/C2F305",
     "publish_date": "2005-02-24", "main_storage_size": 104_000_000, "topics": ["ecg", "arrhythmia"],
     "source_url": "https://physionet.org/content/mitdb/1.0.0/"},
    {"slug": "mimic-iv", "version": "3.1", "is_latest_version": True, "resource_type": "Database",
     "title": "MIMIC-IV", "short_description": "ICU EHR.", "abstract": "", "license": {"name": "PhysioNet Credentialed"},
     "access_policy": "Credentialed", "core_doi": "10.13026/x", "publish_date": "2024-10-11",
     "topics": ["icu"], "source_url": "https://physionet.org/content/mimiciv/3.1/"},
    {"slug": "old", "version": "1.0", "is_latest_version": False, "resource_type": "Database",
     "title": "Old", "source_url": "https://physionet.org/content/old/1.0/"},
    {"slug": "wfdb", "version": "4", "is_latest_version": True, "resource_type": "Software",
     "title": "WFDB", "source_url": "https://physionet.org/content/wfdb/4/"},
]
TCIA = [
    {"link": "https://www.cancerimagingarchive.net/collection/lidc-idri/", "title": {"rendered": "LIDC-IDRI"},
     "collection_short_title": "LIDC-IDRI", "collection_title": "Lung Image Database Consortium",
     "species": ["Human"], "collection_page_accessibility": "Public", "cancer_types": ["Lung Cancer"],
     "collection_abstract": "<p>Thoracic CT with nodule annotations.</p>", "subjects": 1010,
     "data_types": ["CT", "DX"], "collection_doi": "10.7937/K9/TCIA.2015.LO9QL9SX"},
    {"link": "https://www.cancerimagingarchive.net/collection/mouse/", "title": {"rendered": "Mouse"},
     "species": ["Mouse"]},
    {"link": "https://www.cancerimagingarchive.net/collection/restricted/", "title": {"rendered": "R"},
     "collection_short_title": "R-COLL", "species": ["Human"], "collection_page_accessibility": "Limited",
     "cancer_types": ["Non-Cancer"], "collection_abstract": "Healthy breast MRI.", "data_types": ["MR"]},
]


def on_node(id_, name, dx=None):
    return {"node": {"id": id_, "metadata": {"species": "Human", "dxStatus": dx, "modalities": ["eeg"]},
                     "latestSnapshot": {"description": {"Name": name, "DatasetDOI": f"10.18112/openneuro.{id_}",
                                                        "License": "CC0"},
                                        "summary": {"modalities": ["eeg"], "subjects": ["01", "02"],
                                                    "size": 2_000_000_000}}}}


class Session:
    def __init__(self):
        self.calls = []

    def get(self, url, params=None, **kw):
        self.calls.append(url)
        if url == PHYSIONET_API:
            return NS(json=lambda: PHYSIONET, raise_for_status=lambda: None, headers={})
        if url == TCIA_API:
            page = (params or {}).get("page", 1)
            body = TCIA[:2] if page == 1 else TCIA[2:]
            return NS(json=lambda: body, raise_for_status=lambda: None, headers={"X-WP-TotalPages": "2"})
        raise AssertionError(url)

    def post(self, url, json=None, **kw):
        assert url == OPENNEURO_API
        first = json["variables"]["after"] is None
        edges = ([on_node("ds000001", "Balloon analog risk task"),
                  on_node("ds002778", "Parkinson's disease resting-state EEG", dx="Parkinson's")]
                 if first else [on_node("ds004000", "Epilepsy intracranial EEG")])
        body = {"data": {"datasets": {"pageInfo": {"hasNextPage": first, "endCursor": "c1"},
                                      "edges": edges}}}
        return NS(json=lambda: body, raise_for_status=lambda: None)


def runner(tmp_path, client_factory=None):
    settings = Settings(data_dir=tmp_path)
    store = Store(settings.db_path)
    return ImportRunner(store, settings, client_factory=client_factory, session=Session()), store


def test_physionet_import_maps_access_and_skips_old_and_software(tmp_path):
    r, store = runner(tmp_path)
    out = r.run("physionet")
    assert (out["seen"], out["relevant"], out["new"]) == (2, 2, 2)
    by_title = {d["title"]: d for d in store.get_datasets(store.list_dataset_ids())}
    mitdb = by_title["MIT-BIH Arrhythmia Database"]
    assert mitdb["access_type"] == "open" and mitdb["source"] == "PhysioNet"
    assert "wget -r -N -c -np https://physionet.org/files/mitdb/1.0.0/" in mitdb["access_instructions"]
    assert "ambulatory ECG" in mitdb["description"] and "<b>" not in mitdb["description"]
    assert mitdb["download_urls"] == [] and mitdb["found_by"] == "import:physionet"
    assert "10.13026/C2F305" in mitdb["citation"] and mitdb["size"] == "104.0 MB"
    mimic = by_title["MIMIC-IV"]
    assert mimic["access_type"] == "credentialed" and "CITI" in mimic["access_instructions"]
    assert json.loads(store.kv_get("import:physionet"))["state"] == "done"
    # Re-running updates instead of duplicating.
    assert r.run("physionet")["updated"] == 2 and store.stats()["datasets"] == 2


def test_tcia_import_pages_filters_species_and_uses_cancer_types(tmp_path):
    r, store = runner(tmp_path)
    out = r.run("tcia")
    assert out["seen"] == 2 and out["relevant"] == 1   # mouse skipped; "Non-Cancer" w/o signal dropped
    d = store.get_datasets(store.list_dataset_ids())[0]
    assert d["title"] == "LIDC-IDRI: Lung Image Database Consortium"
    assert d["conditions"] == ["lung cancer"] and d["n_subjects"] == "1010"
    assert d["access_type"] == "open" and "NBIA Data Retriever" in d["access_instructions"]


def test_openneuro_keeps_clinical_only_without_llm(tmp_path):
    r, store = runner(tmp_path)
    out = r.run("openneuro")
    assert out["seen"] == 3 and out["relevant"] == 2
    titles = sorted(d["title"] for d in store.get_datasets(store.list_dataset_ids()))
    assert titles == ["Epilepsy intracranial EEG (OpenNeuro ds004000)",
                      "Parkinson's disease resting-state EEG (OpenNeuro ds002778)"]
    d = next(x for x in store.get_datasets(store.list_dataset_ids()) if "ds002778" in x["title"])
    assert "aws s3 sync --no-sign-request s3://openneuro.org/ds002778" in d["access_instructions"]


def test_llm_categorization_decides_relevance_and_conditions(tmp_path):
    class Client:
        def __init__(self):
            self.calls = []
            self.beta = NS(messages=NS(create=self.create))

        def create(self, **kw):
            self.calls.append(kw)
            recs = [json.loads(line) for line in kw["messages"][0]["content"].splitlines()]
            out = [{"id": x["id"], "relevant": "Balloon" not in x["title"],
                    "conditions": ["parkinson's disease"] if "Parkinson" in x["title"] else ["epilepsy"],
                    "modalities": ["eeg"], "labels": ""} for x in recs]
            return response([text(json.dumps({"records": out}))], "end_turn")

    client = Client()
    r, store = runner(tmp_path, client_factory=lambda s: client)
    store.upsert_condition("parkinson's disease")
    out = r.run("openneuro")
    assert out["relevant"] == 2 and out["llm"] is True
    assert "parkinson's disease" in client.calls[0]["system"]   # existing names offered for reuse
    assert client.calls[0]["output_config"]["effort"] == "low"
    d = next(x for x in store.get_datasets(store.list_dataset_ids()) if "ds002778" in x["title"])
    assert d["conditions"] == ["parkinson's disease"] and d["modalities"] == ["eeg"]


def test_heuristic_rejects_nonclinical():
    assert categorize_heuristic({"title": "Face perception fMRI", "description": "", "source": "OpenNeuro",
                                 "hints": {}})["relevant"] is False


def test_import_api(tmp_path):
    import pytest
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from app.main import create_app
    settings = Settings(data_dir=tmp_path, download_enabled=False)
    app = create_app(settings, Store(settings.db_path))
    app.state.importer.session = Session()
    c = TestClient(app)
    assert c.post("/api/imports/nope").status_code == 404
    assert c.post("/api/imports/tcia").status_code == 202
    app.state.importer._thread.join(10)
    st = c.get("/api/imports").json()
    assert st["sources"]["tcia"]["state"] == "done" and st["sources"]["tcia"]["new"] == 1
    assert st["sources"]["physionet"]["label"] == "PhysioNet"


def test_heuristic_ignores_healthy_control_dx():
    rec = {"title": "Go-nogo task", "description": "", "source": "OpenNeuro",
           "hints": {"dx_status": "healthy / control"}}
    assert categorize_heuristic(rec)["relevant"] is False
