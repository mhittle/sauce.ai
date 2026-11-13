import json
from types import SimpleNamespace as NS

from app.compat import (CompatWorker, card_hash, clean_profile, compare, compute_relations,
                        heuristic_profile)
from app.config import Settings
from app.store import Store
from tests.fakes import response, text


def prof(targets, **kw):
    base = {"modality": "chest x-ray", "other_modalities": [], "body_region": "chest",
            "formats": ["png"], "image_size": "1024x1024", "sampling_hz": None, "channels": None,
            "views": "PA/AP frontal", "age_group": "adult", "countries": [], "n_subjects": 30000,
            "targets": [{"name": t, "label_type": lt, "annotator": "expert"} for t, lt in targets]}
    base.update(kw)
    return clean_profile(base)


SIIM = {"id": "siim", "title": "SIIM-ACR Pneumothorax Segmentation", "source": "Kaggle",
        "url": "https://kaggle.com/siim"}
CXR14 = {"id": "cxr14", "title": "NIH ChestX-ray14", "source": "NIH", "url": "https://nih.gov/cxr14"}
P_SIIM = prof([("pneumothorax", "segmentation")], formats=["dicom"])
P_CXR14 = prof([("pneumothorax", "classification")] +
               [(f"finding {i}", "classification") for i in range(13)])


def test_scoring_is_asymmetric_toward_the_focused_dataset():
    siim_view = compare(SIIM, CXR14, P_SIIM, P_CXR14)    # how useful CXR14 is to SIIM users
    cxr_view = compare(CXR14, SIIM, P_CXR14, P_SIIM)      # how useful SIIM is to CXR14 users
    assert siim_view["shared"][0]["target"] == "pneumothorax"
    assert siim_view["score"] > cxr_view["score"]
    assert "external validation" in siim_view["roles"]
    assert any("Validates at the classification level only" in n for n in siim_view["notes"])
    # CXR14 users can derive image-level labels from SIIM's masks.
    assert any("Derive classification labels from its segmentation" in n for n in cxr_view["notes"])
    assert any("Convert png → dicom" in n for n in siim_view["notes"])
    assert any("13 other targets" in n for n in siim_view["notes"])


def test_train_together_needs_same_label_type_and_close_data():
    other = {"id": "pad", "title": "PadChest", "source": "BIMCV", "url": "https://bimcv.es/padchest"}
    rel = compare(CXR14, other, P_CXR14, prof([("pneumothorax", "classification")],
                                              image_size="1100x1100"))
    assert rel["roles"] == ["train together", "external validation"]
    small = compare(CXR14, other, P_CXR14, prof([("pneumothorax", "classification")],
                                                image_size="256x256", age_group="pediatric"))
    assert "train together" not in small["roles"]
    assert any(n.startswith("Resize 256x256") for n in small["notes"])
    assert any(n.startswith("Age mismatch") for n in small["notes"])


def test_shared_cohort_blocks_validation_and_unrelated_modalities_skip():
    a = {"id": "a", "title": "MIMIC-CXR-JPG", "source": "PhysioNet", "url": "https://physionet.org/a"}
    b = {"id": "b", "title": "MIMIC-CXR-LT long-tail labels", "source": "Other", "url": "https://x.org/b"}
    rel = compare(a, b, P_CXR14, P_CXR14)
    assert "external validation" not in rel["roles"] and "MIMIC" in rel["warnings"][0]
    ecg = prof([("atrial fibrillation", "classification")], modality="ecg", formats=["wfdb"],
               image_size="", sampling_hz=500, channels=12, body_region="heart", views="12-lead")
    assert compare(a, b, P_CXR14, ecg) is None


def test_signals_resample_and_pretraining_without_shared_labels():
    ecg500 = prof([("atrial fibrillation", "event")], modality="ecg", formats=["wfdb"], image_size="",
                  sampling_hz=500, channels=12, body_region="heart", views="12-lead")
    ecg360 = prof([("atrial fibrillation", "classification")], modality="ecg", formats=["wfdb"],
                  image_size="", sampling_hz=360, channels=2, body_region="heart", views="ambulatory")
    a = {"id": "a", "title": "PTB-XL", "source": "PhysioNet", "url": "https://physionet.org/ptbxl"}
    b = {"id": "b", "title": "MIT-BIH AF", "source": "PhysioNet", "url": "https://physionet.org/afdb"}
    rel = compare(b, a, ecg360, ecg500)
    assert any("Resample 500 Hz → 360 Hz" in n for n in rel["notes"])
    assert any("12 vs 2 channels" in n for n in rel["notes"])
    unl = prof([("sleep stage", "event")], modality="ecg", formats=["edf"], image_size="",
               sampling_hz=500, body_region="heart")
    pre = compare(a, b, ecg500, unl)
    assert pre["roles"] == ["pretraining"] and pre["score"] <= 35


def test_compute_relations_caps_per_dataset():
    ds = [{"id": f"d{i}", "title": f"Set {i}", "source": f"S{i}", "url": f"https://s{i}.org"}
          for i in range(5)]
    profiles = {d["id"]: P_CXR14 for d in ds}
    rows = compute_relations(ds, profiles, per_dataset=2)
    assert len(rows) == 10 and all(len([r for r in rows if r[0] == d["id"]]) == 2 for d in ds)


def test_heuristic_profile_from_card():
    p = heuristic_profile({"modalities": ["ECG", "wearable accelerometry"], "file_formats": ["EDF"],
                           "conditions": ["atrial fibrillation", "healthy volunteers"],
                           "n_subjects": "1,200 patients"})
    assert p["modality"] == "ecg" and p["other_modalities"] == ["imu"]
    assert p["formats"] == ["edf"] and p["n_subjects"] == 1200
    assert [t["name"] for t in p["targets"]] == ["atrial fibrillation"]


def _cards(store):
    a, _ = store.upsert_dataset({"title": "SIIM-ACR Pneumothorax", "url": "https://kaggle.com/siim",
                                 "source": "Kaggle", "modalities": ["chest x-ray"],
                                 "conditions": ["pneumothorax"]})
    b, _ = store.upsert_dataset({"title": "NIH ChestX-ray14", "url": "https://nih.gov/cxr14",
                                 "source": "NIH", "modalities": ["chest x-ray"],
                                 "conditions": ["pneumothorax", "cardiomegaly", "effusion"]})
    r, _ = store.upsert_dataset({"title": "dbGaP", "url": "https://dbgap.ncbi.nlm.nih.gov/",
                                 "modalities": ["chest x-ray"], "conditions": ["pneumothorax"]})
    return a, b, r


def test_worker_profiles_with_llm_then_relates_and_reprofiles_on_change(tmp_path):
    settings = Settings(data_dir=tmp_path)
    store = Store(settings.db_path)
    a, b, repo = _cards(store)

    class Client:
        calls = 0

        def __init__(self):
            self.beta = NS(messages=NS(create=self.create))

        def create(self, **kw):
            Client.calls += 1
            cards = [json.loads(x) for x in kw["messages"][0]["content"].splitlines()]
            out = [{"id": c["id"], **{k: v for k, v in (P_SIIM if "SIIM" in c["title"] else P_CXR14).items()}}
                   for c in cards]
            return response([text(json.dumps({"profiles": out}))], "end_turn")

    w = CompatWorker(store, settings, client_factory=lambda s: Client())
    assert w.run_until_idle() == 2            # one profiling batch, one recompute
    assert Client.calls == 1
    assert store.get_dataset(repo)["profile"] is None          # repositories aren't profiled
    sa = store.get_dataset(a)
    assert sa["profile"]["source"] == "llm" and sa["n_compatible"] == 1
    rel = store.compatible(a)[0]
    assert rel["id"] == b and rel["shared"][0]["target"] == "pneumothorax"
    assert rel["data"]["image_size"] == "1024x1024"
    assert json.loads(store.kv_get("compat_computed"))["relations"] == 2
    assert w.step() is False                 # idle
    store.upsert_dataset({"url": "https://nih.gov/cxr14", "title": "NIH ChestX-ray14",
                          "description": "Now with bounding boxes."})
    assert w.step() is True and Client.calls == 2              # card changed: re-profiled


def test_worker_without_llm_uses_heuristic_and_api(tmp_path):
    import pytest
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from app.main import create_app
    settings = Settings(data_dir=tmp_path, download_enabled=False)
    store = Store(settings.db_path)
    a, b, _ = _cards(store)
    app = create_app(settings, store)
    app.state.compat.run_until_idle()
    c = TestClient(app)
    body = c.get(f"/api/datasets/{a}/compatible").json()
    assert body["profile"]["source"] == "heuristic"
    assert [x["id"] for x in body["items"]] == [b]
    assert c.get("/api/datasets/nope/compatible").status_code == 404
    assert c.get("/api/compat").json()["last"]["relations"] == 2
    assert card_hash(store.get_dataset(a)) == card_hash(store.get_dataset(a))


def test_control_groups_are_not_targets():
    p = prof([("healthy control", "classification"), ("healthy volunteers", "classification"),
              ("normal", "classification"), ("no finding", "classification"),
              ("alzheimer's disease", "classification")])
    assert [t["name"] for t in p["targets"]] == ["alzheimer's disease"]
    a = {"id": "a", "title": "A", "source": "S", "url": "https://a.org"}
    b = {"id": "b", "title": "B", "source": "S", "url": "https://b.org"}
    raw = {"modality": "eeg", "other_modalities": [], "body_region": "brain", "formats": [],
           "image_size": "", "sampling_hz": None, "channels": None, "views": "",
           "age_group": "adult", "countries": [], "n_subjects": 50,
           "targets": [{"name": "healthy control", "label_type": "classification",
                        "annotator": "clinical"}]}
    rows = compute_relations([a, b], {"a": dict(raw), "b": dict(raw)})
    assert all(r[2]["shared"] == [] for r in rows)        # only same-data-type (pretraining)
