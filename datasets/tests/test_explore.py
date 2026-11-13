import io
import json
import zipfile
from types import SimpleNamespace as NS

import pytest

from app.config import Settings
from app.explore import ExploreManager, heuristic_spec, validate_spec
from app.explore_sources import FilesSource, HFSource, WFDBSource, downsample, pooled, resample
from app.store import Store
from tests.fakes import response, text


def imu_csv(path):
    lines = ["subject_id,time,activity,acc_x,acc_z"]
    for sid in range(1, 7):
        act = "fall" if sid % 2 else "walk"
        for i in range(40):
            ax = 5.0 if (act == "fall" and i == 20) else 0.1 * (i % 3)
            lines.append(f"{sid},{i / 10},{act},{ax},9.8")
    path.write_text("\n".join(lines))
    return path


def image_zip(path):
    with zipfile.ZipFile(path, "w") as z:
        for lab in ("pneumothorax", "normal"):
            for i in range(12):
                z.writestr(f"train/{lab}/{i}.png", b"\x89PNG fake")
        z.writestr("README.txt", "x")
    return path


def test_math_helpers():
    assert len(downsample(list(range(10_000)), 100)) == 100
    assert max(downsample([0] * 5000 + [9] + [0] * 5000, 100)) == 9     # spikes survive
    assert resample([0, 10], 3) == [0, 5, 10]
    assert pooled([[1, 3], [3, 5]]) == {"mean": [2, 4], "sd": [1.41421, 1.41421]}


def test_detect_sources():
    assert HFSource.detect({"url": "https://huggingface.co/datasets/org/name"}) == "org/name"
    assert WFDBSource.detect({"url": "https://physionet.org/content/afdb/1.0.0/",
                              "access_type": "open"}) == "afdb/1.0.0"
    assert WFDBSource.detect({"url": "https://physionet.org/content/mimiciv/3.1/",
                              "access_type": "credentialed"}) is None


def test_files_source_images_by_folder(tmp_path):
    src = FilesSource([image_zip(tmp_path / "imgs.zip")])
    assert src.kind == "images"
    pr = src.probe()
    assert pr["labels"] == {"pneumothorax": 12, "normal": 12}
    page = src.image_rows({"label": "normal"}, 0, 5, lambda i: f"/f/{i}")
    assert page["total"] == 12 and all(r["label"] == "normal" for r in page["rows"])
    assert src.read_bytes(src.images()[0]).startswith(b"\x89PNG")
    spec = heuristic_spec(pr)
    assert [p["type"] for p in spec["panels"]] == ["image_gallery", "label_distribution"]


def test_files_source_table_as_series(tmp_path):
    src = FilesSource([imu_csv(tmp_path / "imu.csv")])
    pr = src.probe()
    assert pr["kind"] == "table" and pr["rows"] == 240
    spec = heuristic_spec(pr)
    assert spec["series"]["id_col"] == "subject_id" and spec["series"]["label_col"] == "activity"
    types = [p["type"] for p in spec["panels"]]
    assert types[:2] == ["signal_viewer", "spaghetti"]
    hist_fields = [p["params"]["field"] for p in spec["panels"] if p["type"] == "histogram"]
    assert "subject_id" not in hist_fields and "time" not in hist_fields
    cfg = spec["series"]
    recs = src.series_records(cfg["id_col"], cfg["label_col"])
    assert len(recs) == 6 and recs[0]["labels"] == ["fall"]
    w = src.series_window(cfg, "1", 0, 2.0)
    assert [c["name"] for c in w["channels"]] == ["acc_x", "acc_z"]
    assert w["annotations"][0]["label"] == "fall"
    tr = src.series_traces(cfg, "acc_x", "fall", 10, None, points=40)
    assert len(tr["traces"]) == 3 and max(tr["pooled"]["mean"]) > 1
    assert src.group_summary(["acc_x"], "activity")["rows"][0]["group"] == "fall"
    assert src.distribution("activity")["groups"][0]["counts"] == {"fall": 120, "walk": 120}


def test_validate_spec_drops_unknown_fields():
    probe = {"kind": "table", "columns": [{"name": "a"}, {"name": "b"}]}
    spec = {"panels": [{"type": "histogram", "title": "ok", "params": {"field": "a"}},
                       {"type": "histogram", "title": "bad", "params": {"field": "zzz"}},
                       {"type": "notes", "title": "n", "params": {"text": "hi"}}], "reply": ""}
    out = validate_spec(spec, probe)
    assert [p["title"] for p in out["panels"]] == ["ok", "n"] and "zzz" in out["reply"]


def _manager(tmp_path, client_factory=None, **kw):
    settings = Settings(data_dir=tmp_path, **kw)
    store = Store(settings.db_path)
    ds, _ = store.upsert_dataset({"title": "IMU falls", "url": "https://x.org/imu",
                                  "access_type": "open", "modalities": ["imu"]})
    f = imu_csv(tmp_path / "imu.csv")
    store.record_file(ds, "https://x.org/imu.csv", "downloaded", filename="imu.csv",
                      local_path=str(f), bytes=f.stat().st_size)
    return ExploreManager(store, settings, client_factory), store, ds


def test_build_edit_revert_with_llm(tmp_path):
    calls = []

    class Client:
        def __init__(self):
            self.beta = NS(messages=NS(create=self.create))

        def create(self, **kw):
            calls.append(kw)
            msg = kw["messages"][0]["content"]
            edit = "User request" in msg
            spec = {"title": "IMU", "summary": "Falls vs walking",
                    "series": {"id_col": "subject_id", "time_col": "time", "label_col": "activity",
                               "channels": ["acc_x", "acc_z"], "fs": 10},
                    "panels": [{"type": "spaghetti", "title": "acc_x", "description": "",
                                "params": {"channel": "acc_x", "labels": ["fall", "walk"]}},
                               {"type": "histogram", "title": "bogus", "description": "",
                                "params": {"field": "nope"}}],
                    "reply": "Added a 3-D trajectory request" if edit else "",
                    "tool_requests": ["3-D trajectory plot of acceleration"] if edit else []}
            return response([text(json.dumps(spec))], "end_turn")

    m, store, ds = _manager(tmp_path, client_factory=lambda s: Client())
    assert m.availability(store.get_dataset(ds)) == {"available": True, "via": "files"}
    spec = m.build_blocking(ds)
    assert [p["title"] for p in spec["panels"]] == ["acc_x"]          # unknown field dropped
    assert "Dataset card" in calls[0]["messages"][0]["content"]
    assert calls[0]["output_config"]["format"]["type"] == "json_schema"
    ex = m.get(ds)
    assert ex["status"] == "ready" and ex["version"] == 1 and ex["source"]["via"] == "files"
    out = m.edit(ds, "show a 3-D trajectory")
    assert out["version"] == 2 and out["tool_requests"] == ["3-D trajectory plot of acceleration"]
    ex = m.get(ds)
    assert ex["requests"][0]["request"].startswith("3-D") and ex["history"][0]["prompt"] == "show a 3-D trajectory"
    m.revert(ds, 1)
    assert m.get(ds)["version"] == 3 and "Restored version 1" in m.get(ds)["spec"]["reply"]


def test_needs_access_and_no_links(tmp_path):
    m, store, _ = _manager(tmp_path)
    locked, _ = store.upsert_dataset({"title": "MIMIC", "url": "https://physionet.org/content/mimiciv/3.1/",
                                      "access_type": "credentialed",
                                      "access_instructions": "Get credentialed."})
    assert m.availability(store.get_dataset(locked))["available"] is False
    with pytest.raises(Exception, match="credentials"):
        m.build_blocking(locked)
    nolinks, _ = store.upsert_dataset({"title": "Open, no files", "url": "https://y.org/",
                                       "access_type": "open"})
    with pytest.raises(Exception, match="No direct download links"):
        m.build_blocking(nolinks)


def test_explore_api_and_token(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from app.main import create_app
    m, store, ds = _manager(tmp_path, download_enabled=False, edit_token="s3cret")
    app = create_app(m.settings, store)
    c = TestClient(app)
    assert c.get(f"/api/explore/{ds}").json()["status"] == "none"
    assert c.post(f"/api/explore/{ds}/build").status_code == 401
    assert c.post(f"/api/explore/{ds}/build", headers={"X-Edit-Token": "s3cret"}).status_code == 202
    app.state.explorer._jobs[ds].join(20)
    d = c.get(f"/api/explore/{ds}").json()
    assert d["status"] == "ready" and d["edit_locked"] is True and "paths" not in d["source"]
    assert c.get(f"/api/explore/{ds}/records", params={"label": "walk"}).json()["total"] == 3
    sig = c.get(f"/api/explore/{ds}/signal", params={"record": "1", "dur": 2}).json()
    assert sig["channels"][0]["name"] == "acc_x"
    tr = c.get(f"/api/explore/{ds}/traces", params={"channel": "acc_x", "label": "fall"}).json()
    assert len(tr["traces"]) == 3
    assert c.get(f"/api/explore/{ds}/distribution", params={"field": "activity"}).json()["type"] == "categorical"
    assert c.get(f"/api/explore/{ds}/rows", params={"length": 3}).json()["total"] == 240
    assert c.post(f"/api/explore/{ds}/edit", json={"prompt": "add stuff"},
                  headers={"X-Edit-Token": "s3cret"}).status_code == 502   # no API key
    assert c.get("/api/explore/nope").status_code == 404
