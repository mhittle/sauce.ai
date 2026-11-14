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
    assert [p["type"] for p in spec["panels"]][:2] == ["image_gallery", "label_distribution"]
    assert spec["panels"][0]["params"]["group_by"] == "label"


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
    with pytest.raises(Exception, match="No open download links"):
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


def ppg_zip(path):
    import pandas as pd
    meta = pd.DataFrame({"Num.": range(1, 13), "subject_ID": range(100, 112),
                         "Age(year)": [40 + i for i in range(12)],
                         "Systolic Blood Pressure(mmHg)": [110 + 5 * i for i in range(12)],
                         "Hypertension": ["Normal"] * 6 + ["Stage 1 hypertension"] * 6})
    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as xw:   # title row above the real header, like PPG-BP
        pd.DataFrame([["Cardiovascular Dataset Information File"]]).to_excel(xw, index=False, header=False)
        meta.to_excel(xw, index=False, startrow=1)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Data File/PPG-BP dataset.xlsx", buf.getvalue())
        for sid in range(100, 112):
            for k in (1, 2):
                amp = 2.0 if sid >= 106 else 1.0
                z.writestr(f"Data File/0_subject/{sid}_{k}.txt",
                           "\t".join(f"{amp * ((i % 50) / 50):.3f}" for i in range(200)))
    return path


def test_one_recording_per_file_with_metadata_join(tmp_path):
    src = FilesSource([ppg_zip(tmp_path / "ppg.zip")])
    assert src.kind == "signals" and len(src.signal_files()) == 24
    pr = src.probe()
    assert pr["records"] == 24 and pr["samples_per_record"] == 200
    assert pr["join"]["id_col"] == "subject_ID" and pr["join"]["label_col"] == "Hypertension"
    assert pr["labels"] == {"Normal": 12, "Stage 1 hypertension": 12}
    assert "Systolic Blood Pressure(mmHg)" in [c["name"] for c in pr["meta"]["columns"]]
    spec = validate_spec(heuristic_spec(pr), pr)
    assert [p["type"] for p in spec["panels"]] == ["signal_viewer", "spaghetti", "label_distribution",
                                                   "group_summary", "record_table"]
    cfg = spec["series"]
    recs = src.file_records(cfg)
    assert recs[0] == {"id": "100_1", "labels": ["Normal"]}
    hi = src.file_traces(cfg, "Stage 1 hypertension", 5, None, points=20)
    lo = src.file_traces(cfg, "Normal", 5, None, points=20)
    assert max(hi["pooled"]["mean"]) > max(lo["pooled"]["mean"])
    w = src.file_window({**cfg, "fs": 100}, "101_2", 0, 1)
    assert w["record_seconds"] == 2.0 and w["channels"][0]["name"] == "signal"
    s = src.group_summary(["Systolic Blood Pressure(mmHg)"], "Hypertension")
    assert s["rows"][0]["Systolic Blood Pressure(mmHg)"]["mean"] == 122.5


def test_chat_queries_the_data(tmp_path):
    from app.explore import ExploreChat

    class Client:
        def __init__(self):
            self.n = 0
            self.beta = NS(messages=NS(create=self.create))

        def create(self, **kw):
            self.n += 1
            if self.n == 1:      # compose (build)
                return response([text(json.dumps(heuristic_spec(m.get(ds)["source"]["probe"])))], "end_turn")
            if self.n == 2:
                return response([NS(type="tool_use", id="t1", name="group_summary",
                                    input={"fields": ["acc_x"], "group_by": "activity"})], "tool_use")
            tool_out = json.loads(kw["messages"][-1]["content"][0]["content"])
            assert tool_out["rows"][0]["group"] == "fall"
            return response([text("Falls have higher mean acc_x.")], "end_turn")

    client = Client()
    m, store, ds = _manager(tmp_path, client_factory=lambda s: client)
    m.build_blocking(ds)
    out = ExploreChat(m).ask(ds, [{"role": "user", "content": "How does acc_x differ by activity?"}])
    assert out == {"answer": "Falls have higher mean acc_x.", "tools_used": ["group_summary"]}
    with pytest.raises(ValueError):
        ExploreChat(m).ask(ds, [{"role": "assistant", "content": "hi"}])


def test_images_join_metadata_table(tmp_path):
    with zipfile.ZipFile(tmp_path / "imgs.zip", "w") as z:
        for i in range(10):
            z.writestr(f"images_part1/case{i}.png", b"\x89PNG")
        z.writestr("dataset.csv", "﻿filestem,fracture_visible,gender\n" +
                   "\n".join(f"case{i},{1 if i < 6 else ''},{'M' if i % 2 else 'F'}" for i in range(10)))
    src = FilesSource([tmp_path / "imgs.zip"])
    pr = src.probe()
    assert pr["kind"] == "images" and pr["metadata_join"] == {"key": "filestem", "matched": 10}
    assert pr["stats"]["fracture_visible"]["frequencies"] == {"1": 6, "(blank)": 4}
    spec = heuristic_spec(pr)
    assert spec["panels"][0]["params"]["group_by"] == "fracture_visible"
    assert src.image_rows({"fracture_visible": "(blank)"}, 0, 50, lambda i: i)["total"] == 4


def test_chat_looks_up_publications_and_web(tmp_path):
    from app.explore import ExploreChat

    class Client:
        def __init__(self):
            self.n, self.calls = 0, []
            self.beta = NS(messages=NS(create=self.create))

        def create(self, **kw):
            self.n += 1
            self.calls.append(kw)
            if self.n == 1:      # compose (build)
                return response([text(json.dumps(heuristic_spec(m.get(ds)["source"]["probe"])))], "end_turn")
            if self.n == 2:
                return response([NS(type="tool_use", id="t1", name="publications",
                                    input={"query": "fall"})], "tool_use")
            if self.n == 3:      # server-side web search paused mid-turn
                lit = json.loads(kw["messages"][-1]["content"][0]["content"])
                assert lit["papers_using_total"] == 1 and [p["title"] for p in lit["papers"]] == ["Fall detection with IMUs"]
                assert lit["papers"][0]["url"] == "https://doi.org/10.1/fall"
                return response([NS(type="server_tool_use", id="s1", name="web_search", input={"query": "x"})],
                                "pause_turn")
            return response([text("See [Fall detection with IMUs](https://doi.org/10.1/fall).")], "end_turn")

    client = Client()
    m, store, ds = _manager(tmp_path, client_factory=lambda s: client)
    for i, (title, rel) in enumerate([("Fall detection with IMUs", "descriptor"), ("Gait speed", "cites")]):
        aid = store.upsert_article({"id": f"doi:10.1/{i}", "title": title, "doi": "10.1/fall" if i == 0 else None,
                                    "year": 2020 + i})
        store.link_article(ds, aid, rel, "test")
    m.build_blocking(ds)
    out = ExploreChat(m).ask(ds, [{"role": "user", "content": "Which papers used this?"}])
    assert out["tools_used"] == ["publications", "web_search"]
    assert "doi.org/10.1/fall" in out["answer"]
    names = [t.get("name") for t in client.calls[1]["tools"]]
    assert {"publications", "fda_devices", "web_search", "web_fetch"} <= set(names)
    lit = ExploreChat(m)._tool(ds, "publications", {"relation": "descriptor"})
    assert [p["relation"] for p in lit["papers"]] == ["descriptor"]
