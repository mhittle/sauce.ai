import io
import json
import zipfile
from pathlib import Path

import numpy as np

from app import explore_repos as R
from app.explore import SPEC_SCHEMA, _unset_to_null
from app.explore_sources import HFSource, SourceError, WFDBSource


def test_spec_schema_has_no_union_types():
    # The API caps anyOf/type-array parameters at 16 per request; staying at
    # zero keeps compose working as the view library grows.
    s = json.dumps(SPEC_SCHEMA)
    assert "anyOf" not in s and '"type": [' not in s


def test_unset_to_null():
    spec = {"panels": [{"type": "histogram", "params": {"field": "age", "group_by": "",
                                                        "bins": 0, "labels": [], "window_sec": 2.5}}],
            "series": {"id_col": "", "time_col": "", "label_col": "", "channels": [], "fs": 0}}
    out = _unset_to_null(spec)
    assert out["panels"][0]["params"] == {"field": "age", "group_by": None, "bins": None,
                                          "labels": None, "window_sec": 2.5}
    assert out["series"] is None
    out = _unset_to_null({"panels": [], "series": {"id_col": "sid", "time_col": "", "label_col": "act",
                                                   "channels": ["x"], "fs": 0}})
    assert out["series"] == {"id_col": "sid", "time_col": None, "label_col": "act",
                             "channels": ["x"], "fs": None}


def test_detect_repositories():
    assert R.openneuro_id({"url": "https://openneuro.org/datasets/ds004504", "source": "OpenNeuro"}) == "ds004504"
    assert R.openneuro_id({"url": "https://example.org/ds004504"}) is None
    R._collections = ["TCGA-KIRC", "LIDC-IDRI"]
    try:
        tcia = {"source": "The Cancer Imaging Archive (TCIA)"}
        assert R.tcia_collection({**tcia, "url": "https://www.cancerimagingarchive.net/collection/tcga-kirc/",
                                  "title": "x"}) == "TCGA-KIRC"
        assert R.tcia_collection({**tcia, "url": "", "title": "LIDC-IDRI: lung nodules"}) == "LIDC-IDRI"
        assert R.tcia_collection({"url": "https://x.org", "title": "TCGA-KIRC"}) is None
    finally:
        R._collections = None


def test_group_column_and_balanced_picks():
    parts = {f"sub-{i:02d}": {"participant_id": f"sub-{i:02d}", "age": str(50 + i),
                              "Group": "A" if i < 6 else "C", "notes": f"n{i}"} for i in range(8)}
    assert R.group_column(parts) == "Group"
    keys = [f"ds/sub-{i:02d}/eeg/sub-{i:02d}_eeg.set" for i in range(8)]
    picks = R._balanced(keys, parts, "Group")
    assert [parts[R._subject(k)]["Group"] for k in picks[:4]] == ["A", "C", "A", "C"]
    # numeric-only columns (durations, scores) are not groups
    assert R.group_column({"sub-1": {"participant_id": "sub-1", "disease": "2"},
                           "sub-2": {"participant_id": "sub-2", "disease": "9"}}) is None


def test_wfdb_roundtrip_with_group_label(tmp_path):
    fs = 100.0
    sig = np.stack([np.sin(np.arange(500) / 10), np.cos(np.arange(500) / 10)], axis=1) * 50
    R.write_wfdb(tmp_path, "sub-01_eeg", ["Fz", "Cz"], fs, sig, ["Group: A", "Age: 61"],
                 [(0.0, "Group=A"), (2.0, "eyes_open")])
    (tmp_path / "RECORDS").write_text("sub-01_eeg\n")
    src = WFDBSource(local_dir=str(tmp_path))
    p = src.probe()
    assert p["source"] == "wfdb" and p["channels"] == ["Fz", "Cz"] and p["fs"] == 100.0
    assert p["labels"] == {"Group=A": 1, "eyes_open": 1}        # sample-0 label kept
    assert "Group: A" in p["header_comments_example"]
    w = src.window("sub-01_eeg", 0, 3)
    assert len(w["channels"]) == 2 and abs(w["channels"][0]["values"][10] - sig[10, 0]) < 1
    assert src.traces(None, "Group=A", 3, 2, "start")["ids"] == ["sub-01_eeg"]


def _edf_bytes(fs=100, n_rec=3, labels=("Fz", "Cz", "EDF Annotations")):
    ns = len(labels)
    head = b"0       " + b" " * 80 + b" " * 80 + b"01.01.2501.01.25" + f"{256 + 256 * ns:<8}".encode()
    head += b" " * 44 + f"{n_rec:<8}".encode() + b"1       " + f"{ns:<4}".encode()
    col = lambda vals, w: b"".join(f"{v:<{w}}".encode() for v in vals)  # noqa: E731
    head += col(labels, 16) + col([""] * ns, 80) + col(["uV"] * ns, 8)
    head += col(["-100"] * ns, 8) + col(["100"] * ns, 8) + col(["-32768"] * ns, 8) + col(["32767"] * ns, 8)
    head += col([""] * ns, 80) + col([fs, fs, 10][:ns], 8) + col([""] * ns, 32)
    data = b""
    for r in range(n_rec):
        for i, _ in enumerate(labels):
            n = fs if i < 2 else 10
            data += np.full(n, 3277 * (i + 1) if i < 2 else 0, dtype="<i2").tobytes()
    return head + data


class FakeHTTP:
    def __init__(self, blobs):
        self.blobs = blobs

    def get(self, url, headers=None, timeout=None, params=None):
        body = self.blobs[url]
        rng = (headers or {}).get("Range")
        status = 200
        if rng:
            a, b = (int(x) for x in rng.split("=")[1].split("-"))
            body, status = body[a: b + 1], 206
        return type("R", (), {"status_code": status, "content": body})()


def test_read_edf_with_range_requests():
    http = FakeHTTP({"u": _edf_bytes()})
    names, fs, sig = R.read_edf(http, "u", seconds=2)
    assert names == ["Fz", "Cz"] and fs == 100 and sig.shape == (200, 2)
    assert abs(sig[0, 0] - 10.0) < 0.1 and abs(sig[0, 1] - 20.0) < 0.1


def test_dicom_series_png(tmp_path):
    import pydicom
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for k in range(5):
            meta = FileMetaDataset()
            meta.TransferSyntaxUID = ExplicitVRLittleEndian
            meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
            meta.MediaStorageSOPInstanceUID = generate_uid()
            d = FileDataset("x", {}, file_meta=meta, preamble=b"\0" * 128)
            d.Rows = d.Columns = 64
            d.BitsAllocated, d.BitsStored, d.HighBit = 16, 16, 15
            d.PixelRepresentation, d.SamplesPerPixel = 1, 1
            d.PhotometricInterpretation = "MONOCHROME2"
            d.InstanceNumber, d.ImagePositionPatient = k + 1, [0, 0, float(k)]
            d.RescaleSlope, d.RescaleIntercept = 1, -1024
            d.PixelData = (np.arange(64 * 64, dtype="<i2").reshape(64, 64) * (k + 1)).tobytes()
            b = io.BytesIO()
            pydicom.dcmwrite(b, d, enforce_file_format=True)
            z.writestr(f"{k:08d}.dcm", b.getvalue())
        z.writestr("LICENSE", "cc-by")
    out = tmp_path / "CT" / "p1.png"
    assert R.dicom_series_png(buf.getvalue(), out) == {"slices": 5}
    from PIL import Image
    im = Image.open(out)
    assert im.size == (256, 256)            # tiny matrices are upscaled


def test_hf_filter_failure_falls_back_to_scanning():
    feats = [{"name": "image", "type": {"_type": "Image"}},
             {"name": "label", "type": {"_type": "ClassLabel", "names": ["NORMAL", "PNEUMONIA"]}}]
    calls = []

    class S(HFSource):
        def _get(self, path, timeout=60, **params):
            calls.append(path)
            if path == "filter":
                raise SourceError("Hugging Face filter: HTTP 500")
            if path == "first-rows":
                return {"features": feats}
            off = params.get("offset", 0)
            return {"num_rows_total": 400, "rows": [
                {"row_idx": i, "row": {"image": {"src": f"https://img/{i}"}, "label": int(i % 4 == 0)}}
                for i in range(off, min(400, off + 100))]}

    s = S("org/cxr")
    s.config, s.split = "default", "train"
    out = s.rows({"label": "PNEUMONIA"}, 0, 5)
    assert [r["label"] for r in out["rows"]] == ["PNEUMONIA"] * 5 and out["total"] == 100
    assert "sampled" in out["note"]
    n = calls.count("rows")
    s.rows({"label": "NORMAL"}, 0, 5)
    assert calls.count("filter") == 1 and calls.count("rows") == n   # filter remembered broken; scan cached


def test_resolve_uses_repository_adapter(tmp_path, monkeypatch):
    from app.config import Settings
    from app.explore import ExploreManager
    from app.store import Store
    settings = Settings(data_dir=tmp_path)
    store = Store(settings.db_path)
    ds, _ = store.upsert_dataset({"title": "EEG AD (OpenNeuro ds004504)", "access_type": "open",
                                  "url": "https://openneuro.org/datasets/ds004504", "source": "OpenNeuro"})
    seen = {}

    def fake_fetch(key, dest, budget, log_):
        seen["key"] = key
        dest.mkdir(parents=True)
        return {"via": "wfdb_local", "dir": str(dest), "repository": "openneuro", "catalog": {"files": 3}}

    import app.explore as E
    monkeypatch.setattr(E, "fetch_openneuro", fake_fetch)
    m = ExploreManager(store, settings)
    assert m.availability(store.get_dataset(ds))["via"] == "openneuro"
    info = m._resolve(store.get_dataset(ds), None, lambda s: None)
    assert seen["key"] == "ds004504" and info["via"] == "wfdb_local"
    m._save(ds, source={**info, "probe": {"x": 1}})
    seen.clear()
    assert m._resolve(store.get_dataset(ds), None, lambda s: None)["via"] == "wfdb_local"
    assert not seen                                                     # reused, not refetched
    assert isinstance(Path(info["dir"]), Path)
