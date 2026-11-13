"""Repository adapters for Explore: fetch a sample through a repository's own
public API instead of searching the web for download links.

- **TCIA** (NBIA REST API, no login for open collections): list a
  collection's series, download a spread of small series (zip of DICOMs),
  render each one's middle slice to PNG, and write an ``images.csv`` with
  modality, body part, series/study description, manufacturer and sex per
  image. The whole collection's series catalog is summarised too (counts
  by modality / body part), since the sample is a small fraction of it.
- **OpenNeuro** (public S3 bucket ``openneuro.org``): ``participants.tsv``
  plus either EEG/iEEG recordings (EDF, BDF, BrainVision, EEGLAB; the first
  few minutes, read with HTTP range requests, converted to WFDB with
  ``events.tsv`` as annotations and participant fields as header comments)
  or anatomical MRI (one T1w per subject, mid-axial slice to PNG, named by
  participant id so it joins ``participants.tsv``).

Each adapter writes under ``<explore>/<id>/raw`` and returns the source info
the explore manager stores (``via`` "files" or "wfdb_local").
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import requests

log = logging.getLogger(__name__)
_UA = {"User-Agent": "pahl-datasets explorer (+https://datasets.paloaltohealthlabs.com)"}
NBIA = "https://services.cancerimagingarchive.net/nbia-api/services/v1"
OPENNEURO_S3 = "https://s3.amazonaws.com/openneuro.org"

IMAGE_MODALITIES = {"CT", "MR", "PT", "CR", "DX", "MG", "US", "NM", "XA", "RF", "OT", "SM"}
_SKIP_SERIES = re.compile(r"localizer|scout|topogram|survey|calibration|dose|protocol|"
                          r"screen ?save|report|summary",
                          re.I)
MAX_SERIES = 60
MAX_SERIES_BYTES = 60_000_000
EEG_SECONDS = 300
MAX_EEG_RECORDINGS = 12
MAX_MRI_SUBJECTS = 40
PNG_MAX = 768

Log = Callable[[str], None]


class RepoError(RuntimeError):
    pass


def _norm(x: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (x or "").lower())


# ------------------------------------------------------------------ TCIA
_collections: list[str] | None = None


def tcia_collection(ds: dict, session: Any = None) -> str | None:
    """The NBIA collection name for a TCIA dataset card, if it has one."""
    global _collections
    text = " ".join(str(ds.get(k) or "") for k in ("url", "source"))
    if "cancerimagingarchive" not in text.lower() and "TCIA" not in text:
        return None
    http = session or requests
    if _collections is None:
        try:
            r = http.get(f"{NBIA}/getCollectionValues", headers=_UA, timeout=30)
            r.raise_for_status()
            _collections = [c["Collection"] for c in r.json()]
        except Exception as exc:
            log.warning("TCIA collection list failed: %s", exc)
            return None
    by_norm = {_norm(c): c for c in _collections}
    cands = []
    m = re.search(r"cancerimagingarchive\.net/collection/([^/?#]+)", ds.get("url") or "")
    if m:
        cands.append(m.group(1))
    title = ds.get("title") or ""
    cands += [title.split(":")[0], title.split(" (")[0], title]
    for c in cands:
        if _norm(c) in by_norm:
            return by_norm[_norm(c)]
    return None


def _render_png(arr, out: Path, invert: bool = False, window: tuple | None = None) -> None:
    import numpy as np
    from PIL import Image
    a = np.asarray(arr)
    if a.ndim == 3 and a.shape[-1] in (3, 4):          # RGB(A)
        img = Image.fromarray(a[..., :3].astype("uint8"))
    else:
        while a.ndim > 2:                               # multi-frame: middle frame
            a = a[a.shape[0] // 2]
        a = a.astype("float32")
        if window:
            lo, hi = window[0] - window[1] / 2, window[0] + window[1] / 2
        else:
            finite = a[np.isfinite(a)]
            lo, hi = (np.percentile(finite, [1, 99]) if finite.size else (0, 1))
        if hi <= lo:
            hi = lo + 1
        a = np.clip((a - lo) / (hi - lo), 0, 1) * 255
        if invert:
            a = 255 - a
        img = Image.fromarray(a.astype("uint8"))
    if max(img.size) < 256:                             # tiny matrices (DWI, PET)
        k = 256 / max(img.size)
        img = img.resize((round(img.width * k), round(img.height * k)), Image.BILINEAR)
    img.thumbnail((PNG_MAX, PNG_MAX))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)


def _first(v):
    try:
        return float(v[0]) if hasattr(v, "__len__") and not isinstance(v, str) else float(v)
    except Exception:
        return None


def dicom_series_png(zip_bytes: bytes, out: Path) -> dict:
    """Render the middle slice of a series (zip of DICOM files) to PNG."""
    import pydicom
    metas = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for name in z.namelist():
            if name.endswith("/") or name.upper() == "LICENSE":
                continue
            try:
                d = pydicom.dcmread(io.BytesIO(z.read(name)), stop_before_pixels=True, force=True)
            except Exception:
                continue
            pos = getattr(d, "ImagePositionPatient", None)
            key = (float(pos[2]) if pos is not None and len(pos) == 3 else
                   float(getattr(d, "InstanceNumber", 0) or 0))
            metas.append((key, name))
        if not metas:
            raise RepoError("no DICOM images in series")
        metas.sort()
        name = metas[len(metas) // 2][1]
        d = pydicom.dcmread(io.BytesIO(z.read(name)), force=True)
    arr = d.pixel_array
    slope = _first(getattr(d, "RescaleSlope", 1)) or 1.0
    icpt = _first(getattr(d, "RescaleIntercept", 0)) or 0.0
    if getattr(d, "PhotometricInterpretation", "") not in ("RGB", "YBR_FULL", "YBR_FULL_422"):
        arr = arr * slope + icpt
    wc, ww = _first(getattr(d, "WindowCenter", None)), _first(getattr(d, "WindowWidth", None))
    _render_png(arr, out, invert=getattr(d, "PhotometricInterpretation", "") == "MONOCHROME1",
                window=(wc, ww) if wc is not None and ww else None)
    return {"slices": len(metas)}


def _spread(series: list[dict], n: int) -> list[dict]:
    """Round-robin across (modality, patient) so the sample covers both."""
    by_mod: dict[str, list[dict]] = {}
    for s in series:
        by_mod.setdefault(s.get("Modality") or "?", []).append(s)
    queues = []
    for mod, items in sorted(by_mod.items(), key=lambda x: -len(x[1])):
        seen, first, rest = set(), [], []
        for s in items:
            (rest if s.get("PatientID") in seen else first).append(s)
            seen.add(s.get("PatientID"))
        queues.append(first + rest)
    out = []
    while len(out) < n and any(queues):
        for q in queues:
            if q and len(out) < n:
                out.append(q.pop(0))
    return out


def fetch_tcia(collection: str, dest: Path, budget: int, log_: Log, session: Any = None) -> dict:
    http = session or requests.Session()
    r = http.get(f"{NBIA}/getSeries", params={"Collection": collection}, headers=_UA, timeout=90)
    if r.status_code != 200:
        raise RepoError(f"TCIA getSeries: HTTP {r.status_code}")
    series = r.json() or []
    if not series:
        raise RepoError("TCIA lists no DICOM series for this collection (it may be "
                        "pathology or analysis results only)")
    sex: dict[str, str] = {}
    try:
        pr = http.get(f"{NBIA}/getPatient", params={"Collection": collection}, headers=_UA,
                      timeout=60)
        sex = {p["PatientId"]: p.get("PatientSex") or "" for p in pr.json() or []}
    except Exception:
        pass
    catalog = {
        "collection": collection, "series": len(series),
        "patients": len({s.get("PatientID") for s in series}),
        "modalities": dict(Counter(s.get("Modality") or "?" for s in series).most_common()),
        "body_parts": dict(Counter(s.get("BodyPartExamined") or "(blank)"
                                   for s in series).most_common(20)),
        "series_descriptions": dict(Counter(s.get("SeriesDescription") or "(blank)"
                                            for s in series).most_common(30)),
    }
    log_(f"TCIA {collection}: {catalog['series']} series from {catalog['patients']} patients "
         f"({', '.join(f'{k} {v}' for k, v in list(catalog['modalities'].items())[:6])})")
    usable = [s for s in series if (s.get("Modality") in IMAGE_MODALITIES)
              and not _SKIP_SERIES.search(s.get("SeriesDescription") or "")
              and 0 < (s.get("FileSize") or 0) <= min(MAX_SERIES_BYTES, budget)]
    if not usable:
        usable = [s for s in series if s.get("Modality") in IMAGE_MODALITIES
                  and 0 < (s.get("FileSize") or 0) <= min(MAX_SERIES_BYTES * 3, budget)]
    # Real volumes first for cross-sectional modalities (a 3-slice CT is
    # usually a reformat or screenshot), then smaller files.
    volumetric = {"CT", "MR", "PT", "NM"}
    usable.sort(key=lambda s: (s.get("Modality") in volumetric and (s.get("ImageCount") or 0) < 20,
                               s.get("FileSize") or 0))
    picks = _spread(usable, MAX_SERIES)
    rows, spent = [], 0
    for i, s in enumerate(picks):
        size = s.get("FileSize") or 0
        if spent + size > budget:
            continue
        stem = re.sub(r"[^\w.-]", "_", f"{s.get('PatientID')}_{s.get('SeriesNumber') or i}_{i}")
        mod = s.get("Modality") or "OT"
        try:
            z = http.get(f"{NBIA}/getImage", params={"SeriesInstanceUID": s["SeriesInstanceUID"]},
                         headers=_UA, timeout=180)
            if z.status_code != 200:
                raise RepoError(f"HTTP {z.status_code}")
            spent += len(z.content)
            info = dicom_series_png(z.content, dest / "images" / mod / f"{stem}.png")
        except Exception as exc:
            log_(f"skipped a {mod} series: {str(exc)[:120]}")
            continue
        rows.append({"image": stem, "patient_id": s.get("PatientID"), "modality": mod,
                     "body_part": s.get("BodyPartExamined") or "",
                     "series_description": "" if s.get("SeriesDescription") in (None, "None")
                     else s["SeriesDescription"],
                     "study_description": s.get("StudyDesc") or "",
                     "manufacturer": s.get("Manufacturer") or "",
                     "sex": sex.get(s.get("PatientID"), ""),
                     "slices": info["slices"]})
        if len(rows) % 10 == 0:
            log_(f"rendered {len(rows)} series ({spent / 1e6:.0f} MB)")
    if not rows:
        raise RepoError("could not render any TCIA series")
    _write_csv(dest / "images.csv", rows)
    log_(f"rendered {len(rows)} series from {len({r['patient_id'] for r in rows})} patients")
    return {"via": "files", "paths": [str(dest)], "repository": "tcia", "catalog": catalog}


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


# ------------------------------------------------------------------ OpenNeuro
def openneuro_id(ds: dict) -> str | None:
    if "openneuro" not in " ".join(str(ds.get(k) or "") for k in ("url", "source")).lower():
        return None
    m = re.search(r"\b(ds\d{6})\b", " ".join(str(ds.get(k) or "") for k in ("url", "title")))
    return m.group(1) if m else None


def s3_keys(ds_id: str, session: Any = None, cap: int = 30000) -> list[tuple[str, int]]:
    http = session or requests
    out, token = [], None
    ns = "{http://s3.amazonaws.com/doc/2006-03-01/}"
    while len(out) < cap:
        params = {"list-type": "2", "prefix": f"{ds_id}/", "max-keys": "1000"}
        if token:
            params["continuation-token"] = token
        r = http.get(OPENNEURO_S3, params=params, headers=_UA, timeout=60)
        if r.status_code != 200:
            raise RepoError(f"OpenNeuro S3 listing: HTTP {r.status_code}")
        root = ET.fromstring(r.content)
        for c in root.iter(f"{ns}Contents"):
            out.append((c.findtext(f"{ns}Key") or "", int(c.findtext(f"{ns}Size") or 0)))
        token = root.findtext(f"{ns}NextContinuationToken")
        if not token:
            break
    return [(k, n) for k, n in out if "/.datalad/" not in k and "/derivatives/" not in k]


def _url(key: str) -> str:
    return f"{OPENNEURO_S3}/{key}"


def _get(http, url: str, rng: tuple[int, int] | None = None, timeout: int = 120) -> bytes:
    headers = dict(_UA)
    if rng:
        headers["Range"] = f"bytes={rng[0]}-{rng[1]}"
    r = http.get(url, headers=headers, timeout=timeout)
    if r.status_code not in (200, 206):
        raise RepoError(f"HTTP {r.status_code} for {url.rsplit('/', 1)[-1]}")
    return r.content


def _participants(text: str) -> dict[str, dict]:
    rows = list(csv.DictReader(io.StringIO(text), delimiter="\t"))
    return {r.get("participant_id", ""): r for r in rows if r.get("participant_id")}


def group_column(parts: dict[str, dict]) -> str | None:
    """The participants.tsv column holding the study group (diagnosis, group...)."""
    if not parts:
        return None
    cols = [c for c in next(iter(parts.values())) if c != "participant_id"]
    best = None
    for c in cols:
        vals = {r.get(c) for r in parts.values()} - {"", "n/a", None}
        if all(re.fullmatch(r"-?\d+(\.\d+)?", str(v)) for v in vals):
            continue                    # numeric (age, duration, scores)
        if 2 <= len(vals) <= 8:
            score = 2 if re.search(r"group|diagnos|\bdx\b|condition|status|cohort|patient|"
                                   r"clinical|disease|type", c, re.I) else 0
            if best is None or score > best[0]:
                best = (score, c)
    return best[1] if best and best[0] else None


def _balanced(keys: list[str], parts: dict[str, dict], col: str | None) -> list[str]:
    """One key per subject, round-robin across the study groups."""
    by_group: dict[str, list[str]] = {}
    seen = set()
    for k in keys:
        sub = _subject(k)
        if sub in seen:
            continue
        seen.add(sub)
        g = str((parts.get(sub) or {}).get(col, "")) if col else ""
        by_group.setdefault(g, []).append(k)
    queues = list(by_group.values())
    out = []
    while any(queues):
        for q in queues:
            if q:
                out.append(q.pop(0))
    return out


def _subject(key: str) -> str:
    m = re.search(r"(sub-[A-Za-z0-9]+)", key)
    return m.group(1) if m else ""


# -- EEG readers: (channel names, fs, signal [samples x channels] in physical units)
def read_edf(http, url: str, seconds: int = EEG_SECONDS):
    import numpy as np
    head = _get(http, url, (0, 255))
    ns = int(head[252:256].decode().strip())
    hdr = head + _get(http, url, (256, 256 + ns * 256 - 1))
    bdf = hdr[0] == 255
    f = lambda off, w: [hdr[256 + off * ns + i * w: 256 + off * ns + (i + 1) * w]  # noqa: E731
                        .decode("latin-1").strip() for i in range(ns)]
    labels = f(0, 16)
    pmin, pmax = [float(x) for x in f(104, 8)], [float(x) for x in f(112, 8)]
    dmin, dmax = [float(x) for x in f(120, 8)], [float(x) for x in f(128, 8)]
    nsamp = [int(x) for x in f(216, 8)]
    rec_dur = float(hdr[244:252].decode().strip() or 1) or 1.0
    n_rec = int(hdr[236:244].decode().strip() or -1)
    # Keep the channels sharing the most common rate (drop annotations/aux).
    keep = [i for i in range(ns) if "annotation" not in labels[i].lower()]
    rate = Counter(nsamp[i] for i in keep).most_common(1)[0][0]
    keep = [i for i in keep if nsamp[i] == rate]
    bps = 3 if bdf else 2
    rec_bytes = sum(nsamp) * bps
    want = max(1, int(seconds / rec_dur))
    if n_rec > 0:
        want = min(want, n_rec)
    raw = _get(http, url, (256 + ns * 256, 256 + ns * 256 + want * rec_bytes - 1), timeout=300)
    want = len(raw) // rec_bytes
    if bdf:
        b = np.frombuffer(raw[: want * rec_bytes], dtype=np.uint8).reshape(-1, 3)
        vals = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8)
                | (b[:, 2].astype(np.int32) << 16))
        vals = np.where(vals >= 1 << 23, vals - (1 << 24), vals)
    else:
        vals = np.frombuffer(raw[: want * rec_bytes], dtype="<i2").astype(np.int32)
    vals = vals.reshape(want, sum(nsamp))
    starts = np.cumsum([0] + nsamp[:-1])
    cols = []
    for i in keep:
        d = vals[:, starts[i]: starts[i] + nsamp[i]].reshape(-1).astype("float64")
        gain = (pmax[i] - pmin[i]) / ((dmax[i] - dmin[i]) or 1)
        cols.append((d - dmin[i]) * gain + pmin[i])
    return [labels[i] for i in keep], rate / rec_dur, np.stack(cols, axis=1)


def read_brainvision(http, url_vhdr: str, seconds: int = EEG_SECONDS):
    import configparser
    import numpy as np
    text = _get(http, url_vhdr).decode("utf-8", "ignore")
    text = text[text.find("["):]
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.read_string(text)
    common = cp["Common Infos"]
    nch = int(common.get("NumberOfChannels"))
    fs = 1e6 / float(common.get("SamplingInterval"))
    if common.get("DataOrientation", "MULTIPLEXED").upper() != "MULTIPLEXED":
        raise RepoError("vectorized BrainVision data not supported")
    fmt = cp["Binary Infos"].get("BinaryFormat", "INT_16").upper()
    dt, size = {"INT_16": ("<i2", 2), "INT_32": ("<i4", 4),
                "IEEE_FLOAT_32": ("<f4", 4)}.get(fmt, ("<i2", 2))
    names, res = [], []
    for i in range(1, nch + 1):
        parts = (cp["Channel Infos"].get(f"Ch{i}") or f"Ch{i}").split(",")
        names.append(parts[0].replace(r"\1", ","))
        res.append(float(parts[2]) if len(parts) > 2 and parts[2] else 1.0)
    data_url = url_vhdr.rsplit("/", 1)[0] + "/" + common.get("DataFile")
    n = int(seconds * fs)
    raw = _get(http, data_url, (0, n * nch * size - 1), timeout=300)
    arr = np.frombuffer(raw[: (len(raw) // (nch * size)) * nch * size], dtype=dt)
    return names, fs, arr.reshape(-1, nch).astype("float64") * np.array(res)


def read_eeglab(http, url_set: str, seconds: int = EEG_SECONDS, max_set_bytes: int = 40_000_000):
    import numpy as np
    import scipy.io
    raw = _get(http, url_set, timeout=300)
    if len(raw) > max_set_bytes:
        raise RepoError(".set file too large")
    try:
        m = scipy.io.loadmat(io.BytesIO(raw), squeeze_me=True, struct_as_record=False)
    except NotImplementedError as exc:   # v7.3 / HDF5
        raise RepoError("EEGLAB v7.3 files not supported") from exc
    eeg = m.get("EEG")
    get = (lambda k: getattr(eeg, k)) if eeg is not None else (lambda k: m[k])
    nch, fs = int(get("nbchan")), float(get("srate"))
    try:
        locs = get("chanlocs")
        names = [str(getattr(c, "labels", f"Ch{i + 1}")) for i, c in enumerate(np.atleast_1d(locs))]
    except Exception:
        names = []
    names = names if len(names) == nch else [f"Ch{i + 1}" for i in range(nch)]
    data = get("data")
    n = int(seconds * fs)
    if isinstance(data, str):            # separate .fdt: float32, channel-fastest
        fdt = url_set.rsplit("/", 1)[0] + "/" + data
        b = _get(http, fdt, (0, n * nch * 4 - 1), timeout=300)
        arr = np.frombuffer(b[: (len(b) // (nch * 4)) * nch * 4], dtype="<f4").reshape(-1, nch)
    else:
        arr = np.asarray(data, dtype="float64")
        if arr.ndim == 3:                # epoched: concatenate epochs
            arr = arr.reshape(nch, -1)
        arr = arr[:, :n].T
    return names, fs, arr.astype("float64")


EEG_READERS = {".edf": read_edf, ".bdf": read_edf, ".vhdr": read_brainvision, ".set": read_eeglab}


def _events(http, keys: set[str], rec_key: str) -> list[tuple[float, str]]:
    base = re.sub(r"_(eeg|ieeg)\.\w+$", "_events.tsv", rec_key)
    if base not in keys:
        return []
    try:
        text = _get(http, _url(base), timeout=60).decode("utf-8", "ignore")
    except Exception:
        return []
    out = []
    for r in csv.DictReader(io.StringIO(text), delimiter="\t"):
        try:
            t = float(r.get("onset") or "nan")
        except ValueError:
            continue
        lab = r.get("trial_type") or r.get("value") or r.get("event_type") or ""
        if t == t and lab and lab != "n/a":
            out.append((t, str(lab)[:40]))
    return out


def write_wfdb(out_dir: Path, name: str, names: list[str], fs: float, sig, comments: list[str],
               events: list[tuple[float, str]]) -> None:
    import numpy as np
    import wfdb
    out_dir.mkdir(parents=True, exist_ok=True)
    sig = np.nan_to_num(sig[:, :128])
    names = [re.sub(r"[^\w.+-]", "_", n)[:20] or f"ch{i}" for i, n in enumerate(names[:128])]
    wfdb.wrsamp(name, fs=round(fs, 4), units=["uV"] * len(names), sig_name=names,
                p_signal=sig, fmt=["16"] * len(names), comments=comments[:30],
                write_dir=str(out_dir))
    n = sig.shape[0]
    # wfdb silently drops an annotation at sample 0
    ev = [(max(1, int(t * fs)), lab) for t, lab in events if 0 <= t * fs < n]
    if ev:
        wfdb.wrann(name, "atr", np.array([s for s, _ in ev]), symbol=['"'] * len(ev),
                   aux_note=[lab for _, lab in ev], fs=fs, write_dir=str(out_dir))


def mri_png(http, key: str, out: Path) -> None:
    import nibabel as nib
    import numpy as np
    raw = _get(http, _url(key), timeout=300)
    fh = nib.FileHolder(fileobj=io.BytesIO(raw))
    gz = key.endswith(".gz")
    if gz:
        import gzip
        fh = nib.FileHolder(fileobj=io.BytesIO(gzip.decompress(raw)))
    img = nib.Nifti1Image.from_file_map({"header": fh, "image": fh})
    img = nib.as_closest_canonical(img)
    a = np.asarray(img.dataobj, dtype="float32")
    while a.ndim > 3:
        a = a[..., 0]
    sl = np.rot90(a[:, :, a.shape[2] // 2])     # mid-axial, anterior up
    _render_png(sl, out)


def fetch_openneuro(ds_id: str, dest: Path, budget: int, log_: Log, session: Any = None) -> dict:
    http = session or requests.Session()
    listing = s3_keys(ds_id, http)
    if not listing:
        raise RepoError("OpenNeuro listing is empty")
    keys = {k for k, _ in listing}
    sizes = dict(listing)
    log_(f"OpenNeuro {ds_id}: {len(listing)} files listed")
    parts: dict[str, dict] = {}
    pkey = f"{ds_id}/participants.tsv"
    if pkey in keys:
        text = _get(http, _url(pkey), timeout=60).decode("utf-8", "ignore")
        (dest / "participants.tsv").parent.mkdir(parents=True, exist_ok=True)
        (dest / "participants.tsv").write_text(text)
        parts = _participants(text)
    catalog = {"dataset": ds_id, "files": len(listing),
               "subjects": len({_subject(k) for k in keys if _subject(k)}),
               "suffixes": dict(Counter(re.sub(r"^.*_", "", k.rsplit("/", 1)[-1])
                                        for k in keys if "/sub-" in k).most_common(15))}

    gcol = group_column(parts)
    if not gcol and parts:   # e.g. sub-hc1 / sub-pd3: the group is in the id
        pref = {p: (re.match(r"sub-([A-Za-z]+)\d", p) or [None, ""])[1].lower() for p in parts}
        if 2 <= len(set(pref.values()) - {""}) <= 6:
            gcol = "group"
            for p, r in parts.items():
                r["group"] = pref[p]
    if gcol:
        catalog["group_column"] = gcol
        catalog["groups"] = dict(Counter(r.get(gcol) for r in parts.values()).most_common())
    eeg = [k for k in sorted(keys) if re.search(r"_(eeg|ieeg)\.(edf|bdf|vhdr|set)$", k)]
    if eeg:
        picks = _balanced(eeg, parts, gcol)
        out_dir, done, spent = dest / "wfdb", [], 0
        for k in picks:
            if len(done) >= MAX_EEG_RECORDINGS or spent > budget:
                break
            ext = "." + k.rsplit(".", 1)[-1]
            try:
                names, fs, sig = EEG_READERS[ext](http, _url(k))
            except Exception as exc:
                log_(f"skipped {k.rsplit('/', 1)[-1]}: {str(exc)[:120]}")
                continue
            spent += sig.nbytes // 4
            sub = _subject(k)
            meta = {kk: v for kk, v in (parts.get(sub) or {}).items()
                    if kk != "participant_id" and v not in ("", "n/a")}
            comments = [f"{kk}: {v}" for kk, v in list(meta.items())[:20]]
            name = re.sub(r"[^\w-]", "_", k.rsplit("/", 1)[-1].rsplit(".", 1)[0])[:60]
            events = _events(http, keys, k)
            if gcol and meta.get(gcol):   # whole-record label: the subject's group
                events = [(0.0, f"{gcol}={meta[gcol]}")] + events
            keep = [i for i, n in enumerate(names) if n.lower() not in ("status", "trigger")]
            write_wfdb(out_dir, name, [names[i] for i in keep], fs, sig[:, keep], comments,
                       events)
            done.append(name)
            log_(f"converted {name} ({len(names)} ch, {fs:g} Hz, {sig.shape[0] / fs:.0f} s)")
        if done:
            (out_dir / "RECORDS").write_text("\n".join(done) + "\n")
            return {"via": "wfdb_local", "dir": str(out_dir), "repository": "openneuro",
                    "catalog": {**catalog, "eeg_recordings": len(eeg),
                                "sampled_seconds": EEG_SECONDS}}

    anat = [k for k in sorted(keys) if re.search(r"/anat/[^/]*_T1w\.nii(\.gz)?$", k)] or \
           [k for k in sorted(keys) if re.search(r"/anat/[^/]*\.nii(\.gz)?$", k)]
    if anat:
        picks = _balanced(anat, parts, gcol)
        n, spent = 0, 0
        for k in picks:
            if n >= MAX_MRI_SUBJECTS or spent + sizes.get(k, 0) > budget:
                continue
            sub = _subject(k)
            suffix = re.sub(r"\.nii(\.gz)?$", "", k.rsplit("_", 1)[-1])
            try:
                mri_png(http, k, dest / "images" / suffix / f"{sub}.png")
            except Exception as exc:
                log_(f"skipped {k.rsplit('/', 1)[-1]}: {str(exc)[:120]}")
                continue
            spent += sizes.get(k, 0)
            n += 1
            if n % 10 == 0:
                log_(f"rendered {n} anatomical scans ({spent / 1e6:.0f} MB)")
        if n:
            log_(f"rendered {n} anatomical scans")
            return {"via": "files", "paths": [str(dest)], "repository": "openneuro",
                    "catalog": catalog}

    if parts:
        log_("no EEG or anatomical MRI to sample; using participants.tsv")
        return {"via": "files", "paths": [str(dest)], "repository": "openneuro",
                "catalog": catalog}
    raise RepoError("nothing readable found (no EEG, anatomical MRI or participants.tsv)")
