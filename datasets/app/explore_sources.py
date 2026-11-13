"""Data sources for Explore: a small, uniform way to read samples of a
dataset wherever it lives, so every explore view works the same way.

Three kinds of data, three access patterns:

- ``images``: rows with an image (and optional mask) plus label fields —
  :class:`HFSource` (Hugging Face datasets-server API) and image folders in
  local/acquired files (:class:`FilesSource`; label = parent folder name).
- ``signals``: records of multi-channel waveforms with time annotations —
  :class:`WFDBSource` (PhysioNet open databases, streamed with ``wfdb``).
- ``table``: rows and columns — CSV/TSV/TXT in local/acquired files, possibly
  inside zips (:class:`FilesSource`). A table can also be read as *series*
  (one record per subject/trial id, ordered by a time column), which is how
  IMU or other sensor CSVs feed the signal and spaghetti views.

Every source has ``probe()`` (a compact description of fields, labels and
sizes, used by Claude to compose the explore spec and by the UI) and the
reader methods its kind supports. Nothing here calls an LLM.
"""
from __future__ import annotations

import io
import json
import logging
import math
import re
import time
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

log = logging.getLogger(__name__)
_UA = {"User-Agent": "pahl-datasets explorer (+https://datasets.paloaltohealthlabs.com)"}
HF_SERVER = "https://datasets-server.huggingface.co"
MAX_POINTS = 2000          # per channel per window returned to the browser
TABLE_MAX_ROWS = 200_000   # rows read from one table file
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff")
TABLE_EXT = (".csv", ".tsv", ".txt", ".xlsx", ".xls")
_NUM_TOKEN = re.compile(r"^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$")


class SourceError(RuntimeError):
    pass


def downsample(values: list[float], n: int = MAX_POINTS) -> list[float]:
    """Min/max decimation that keeps peaks (QRS spikes, impacts) visible."""
    if len(values) <= n:
        return [None if (v is None or (isinstance(v, float) and math.isnan(v))) else round(float(v), 5)
                for v in values]
    step = len(values) / (n // 2)
    out = []
    for i in range(n // 2):
        chunk = [v for v in values[int(i * step):int((i + 1) * step)]
                 if v is not None and not (isinstance(v, float) and math.isnan(v))]
        if chunk:
            out += [round(float(min(chunk)), 5), round(float(max(chunk)), 5)]
        else:
            out += [None, None]
    return out


def resample(values: list[float], n: int) -> list[float]:
    """Linear resampling to n points (for overlaying traces of different lengths)."""
    vals = [float(v) for v in values if v is not None and not math.isnan(float(v))]
    if not vals:
        return [None] * n
    if len(vals) == 1:
        return vals * n
    out = []
    for i in range(n):
        x = i * (len(vals) - 1) / (n - 1)
        lo = int(x)
        hi = min(lo + 1, len(vals) - 1)
        out.append(round(vals[lo] + (vals[hi] - vals[lo]) * (x - lo), 5))
    return out


def pooled(traces: list[list[float]]) -> dict:
    """Mean and SD across equal-length traces, point by point."""
    if not traces:
        return {"mean": [], "sd": []}
    n = len(traces[0])
    mean, sd = [], []
    for i in range(n):
        col = [t[i] for t in traces if t[i] is not None]
        if not col:
            mean.append(None)
            sd.append(None)
            continue
        m = sum(col) / len(col)
        mean.append(round(m, 5))
        sd.append(round(math.sqrt(sum((x - m) ** 2 for x in col) / max(1, len(col) - 1)), 5))
    return {"mean": mean, "sd": sd}


# ------------------------------------------------------------------ Hugging Face
class HFSource:
    """A Hugging Face dataset via the public datasets-server API: rows, image
    and mask URLs, class-label names, column statistics, server-side filter."""

    kind = "images"

    def __init__(self, repo: str, session: Any = None):
        self.repo = repo
        self.http = session or requests.Session()
        self.config: str | None = None
        self.split: str | None = None
        self._features: list[dict] | None = None

    @staticmethod
    def detect(ds: dict) -> str | None:
        for u in [ds.get("url") or "", *(ds.get("download_urls") or [])]:
            m = re.match(r"https?://huggingface\.co/datasets/([\w.-]+/[\w.-]+)", u)
            if m:
                return m.group(1)
        return None

    def _get(self, path: str, timeout: float = 60, **params) -> dict:
        try:
            r = self.http.get(f"{HF_SERVER}/{path}", params={"dataset": self.repo, **params},
                              headers=_UA, timeout=timeout)
        except requests.RequestException as exc:
            raise SourceError(f"Hugging Face {path}: {type(exc).__name__}") from exc
        if r.status_code != 200:
            raise SourceError(f"Hugging Face {path}: HTTP {r.status_code}")
        return r.json()

    def _choose_split(self) -> None:
        if self.split:
            return
        splits = self._get("splits").get("splits") or []
        if not splits:
            raise SourceError("no splits on Hugging Face")
        pick = next((s for s in splits if s["split"] == "train"), splits[0])
        self.config, self.split = pick["config"], pick["split"]

    def features(self) -> list[dict]:
        if self._features is None:
            self._choose_split()
            body = self._get("first-rows", config=self.config, split=self.split)
            self._features = body.get("features") or []
        return self._features

    def probe(self) -> dict:
        feats = self.features()
        fields = []
        for f in feats:
            t = f["type"]
            kind = ("image" if t.get("_type") == "Image" else
                    "class_label" if t.get("_type") == "ClassLabel" else
                    "number" if t.get("dtype", "").startswith(("int", "float")) else
                    "text" if t.get("dtype") == "string" else t.get("_type", "other"))
            fields.append({"name": f["name"], "kind": kind,
                           "names": t.get("names") if kind == "class_label" else None})
        stats = {}
        try:
            body = self._get("statistics", config=self.config, split=self.split)
            for col in body.get("statistics", []):
                cs = col.get("column_statistics") or {}
                stats[col["column_name"]] = {
                    "type": col.get("column_type"),
                    "frequencies": cs.get("frequencies"),
                    "min": cs.get("min"), "max": cs.get("max"), "mean": cs.get("mean"),
                    "n_unique": cs.get("n_unique"), "histogram": cs.get("histogram")}
            n_rows = body.get("num_examples")
        except SourceError:
            n_rows = None
        # Small integer columns (0/1 flags, class ids) act as labels too. When
        # the statistics endpoint has nothing, flag-like names decide, and
        # counts come from the filter endpoint.
        for f in fields:
            st = stats.get(f["name"]) or {}
            flaggy = re.search(r"^(has|is)_|label|class|target|diagnos|finding|^y$", f["name"], re.I)
            if f["kind"] == "number" and ((st.get("n_unique") and st["n_unique"] <= 12)
                                          or (not st and flaggy)):
                f["kind"] = "label_number"
                if not st.get("frequencies"):
                    freqs = {}
                    for v in range(0, 12 if not re.search(r"^(has|is)_", f["name"]) else 2):
                        try:
                            n = self._get("filter", timeout=25, config=self.config,
                                          split=self.split, where=f'"{f["name"]}"={v}',
                                          length=1).get("num_rows_total")
                        except SourceError:
                            break
                        if n:
                            freqs[str(v)] = n
                        elif v > 1:
                            break
                    if freqs:
                        stats[f["name"]] = {**st, "type": "label_number", "frequencies": freqs}
        return {"source": "huggingface", "kind": "images", "repo": self.repo,
                "config": self.config, "split": self.split, "rows": n_rows,
                "fields": fields, "stats": stats}

    def rows(self, where: dict | None = None, offset: int = 0, length: int = 24) -> dict:
        """Rows (optionally where field == value), images as URLs."""
        self._choose_split()
        feats = {f["name"]: f["type"] for f in self.features()}
        length = max(1, min(100, length))
        if where:
            clauses = []
            for k, v in where.items():
                t = feats.get(k, {})
                if t.get("_type") == "ClassLabel" and not str(v).lstrip("-").isdigit():
                    v = (t.get("names") or []).index(v) if v in (t.get("names") or []) else v
                val = v if str(v).lstrip("-").replace(".", "", 1).isdigit() else f"'{v}'"
                clauses.append(f'"{k}"={val}')
            try:
                if getattr(self, "_filter_broken", False):
                    raise SourceError("Hugging Face filter: unavailable")
                body = self._get("filter", timeout=25, config=self.config, split=self.split,
                                 where=" AND ".join(clauses), offset=offset, length=length)
            except SourceError as exc:
                self._filter_broken = True
                # The filter endpoint 500s on some (often image-heavy) datasets:
                # fall back to scanning spread-out pages of /rows.
                log.info("HF filter failed for %s (%s); scanning rows", self.repo, exc)
                matches, total = self._scan(where)
                return {"rows": matches[offset: offset + length], "total": total,
                        "note": "sampled: the Hugging Face filter is unavailable for this dataset"}
        else:
            body = self._get("rows", config=self.config, split=self.split,
                             offset=offset, length=length)
        return {"rows": self._convert(body.get("rows", [])), "total": body.get("num_rows_total")}

    SCAN_PAGES = 24

    def _scan(self, where: dict) -> tuple[list[dict], int]:
        rows, n = self._scan_rows()
        want = {k: str(v) for k, v in where.items()}
        matches = [r for r in rows if all(str(r.get(k)) == v for k, v in want.items())]
        total = round(len(matches) * n / len(rows)) if rows and n else len(matches)
        return matches, total

    def _scan_rows(self) -> tuple[list[dict], int]:
        """Pages spread evenly across the split, fetched once for every label
        (cached ~20 min: image URLs from the API are signed and expire)."""
        import threading
        from concurrent.futures import ThreadPoolExecutor
        lock = self.__dict__.setdefault("_scan_lock", threading.Lock())
        with lock:
            hit = getattr(self, "_scan_hit", None)
            if hit and time.time() - hit[0] < 1200:
                return hit[1], hit[2]
            first = self._get("rows", config=self.config, split=self.split, offset=0, length=100)
            n = first.get("num_rows_total") or len(first.get("rows", []))
            offsets = sorted({min(max(0, n - 100), int(i * n / self.SCAN_PAGES))
                              for i in range(self.SCAN_PAGES)}) if n > 100 else [0]

            def page(off: int) -> list[dict]:
                try:
                    body = first if off == 0 else self._get(
                        "rows", timeout=40, config=self.config, split=self.split,
                        offset=off, length=100)
                except SourceError:
                    return []
                return self._convert(body.get("rows", []))

            with ThreadPoolExecutor(max_workers=8) as pool:
                rows = [r for chunk in pool.map(page, offsets) for r in chunk]
            self._scan_hit = (time.time(), rows, n)
            return rows, n

    def _convert(self, raw_rows: list[dict]) -> list[dict]:
        feats = {f["name"]: f["type"] for f in self.features()}
        out = []
        for r in raw_rows:
            row = {"index": r.get("row_idx")}
            for k, v in r["row"].items():
                t = feats.get(k, {})
                if t.get("_type") == "Image":
                    row[k] = (v or {}).get("src") if isinstance(v, dict) else None
                elif t.get("_type") == "ClassLabel" and isinstance(v, int):
                    names = t.get("names") or []
                    row[k] = names[v] if 0 <= v < len(names) else v
                elif isinstance(v, (int, float, str, bool)) or v is None:
                    row[k] = v
            out.append(row)
        return out


# ------------------------------------------------------------------ PhysioNet WFDB
class WFDBSource:
    """An open PhysioNet WFDB database, streamed record by record."""

    kind = "signals"
    ANN_EXTS = ("atr", "qrs", "apn", "ecg", "arousal", "st", "event", "ann", "pwave")

    def __init__(self, pn_dir: str | None = None, local_dir: str | None = None):
        self.pn_dir = pn_dir
        self.local_dir = local_dir      # WFDB records we converted (e.g. OpenNeuro EEG)
        self._ann_ext: str | None = None
        self._ann_cache: dict[str, Any] = {}

    @staticmethod
    def detect(ds: dict) -> str | None:
        if ds.get("access_type") != "open":
            return None
        m = re.match(r"https?://physionet\.org/content/([\w.-]+)/([\w.-]+)/?", ds.get("url") or "")
        return f"{m.group(1)}/{m.group(2)}" if m else None

    def _wfdb(self):
        try:
            import wfdb
        except ImportError as exc:  # pragma: no cover
            raise SourceError("wfdb is not installed") from exc
        return wfdb

    def records(self) -> list[str]:
        if self.local_dir:
            f = Path(self.local_dir) / "RECORDS"
            return [ln.strip() for ln in f.read_text().splitlines() if ln.strip()] \
                if f.exists() else []
        try:
            return self._wfdb().get_record_list(self.pn_dir)
        except Exception as exc:
            raise SourceError(f"PhysioNet record list: {exc}") from exc

    def annotations(self, record: str) -> list[dict]:
        """[{t (seconds), symbol, label}] where label is the rhythm/aux note
        when present, else the beat symbol."""
        if record in self._ann_cache:
            return self._ann_cache[record]
        wfdb = self._wfdb()
        exts = [self._ann_ext] if self._ann_ext else list(self.ANN_EXTS)
        out: list[dict] = []
        for ext in exts:
            if not ext:
                continue
            name, pn = self._split(record)
            try:
                a = wfdb.rdann(name, ext, pn_dir=pn)
            except Exception:
                continue
            self._ann_ext = ext
            fs = a.fs or 1
            for s, sym, aux in zip(a.sample, a.symbol, a.aux_note or [""] * len(a.sample)):
                aux = (aux or "").strip("\x00").strip()
                out.append({"t": round(float(s) / fs, 3), "symbol": sym,
                            "label": aux.lstrip("(") if aux else sym})
            break
        self._ann_cache[record] = out
        return out

    def _split(self, record: str) -> tuple[str, str]:
        """RECORDS entries can include subfolders (`tpehgdb/tpehg1039`); wfdb
        wants the folder in pn_dir and the bare record name."""
        if self.local_dir:
            return str(Path(self.local_dir) / record), None
        folder, _, name = record.rpartition("/")
        return name, f"{self.pn_dir}/{folder}" if folder else self.pn_dir

    def header(self, record: str) -> dict:
        cache = self.__dict__.setdefault("_hdr", {})
        if record in cache:
            return cache[record]
        name, pn = self._split(record)
        try:
            h = self._wfdb().rdheader(name, pn_dir=pn)
        except Exception as exc:
            raise SourceError(f"header {record}: {exc}") from exc
        cache[record] = {"fs": float(h.fs), "channels": list(h.sig_name or []),
                         "units": list(h.units or []),
                         "seconds": round((h.sig_len or 0) / float(h.fs), 1),
                         # Many databases keep per-record metadata here (age,
                         # sex, diagnosis, gestation...).
                         "comments": [str(c)[:200] for c in (h.comments or [])][:40]}
        return cache[record]

    def probe(self, max_records: int = 25) -> dict:
        recs = self.records()
        first: dict = {}
        for r in recs[:8]:        # some records carry annotations only
            try:
                first = self.header(r)
            except SourceError:
                continue
            if first.get("channels"):
                break
        labels: dict[str, int] = {}
        per_record: dict[str, list[str]] = {}
        for r in recs[:max_records]:
            anns = self.annotations(r)
            seen = sorted({a["label"] for a in anns})
            per_record[r] = seen
            for lab in seen:
                labels[lab] = labels.get(lab, 0) + 1
        return {"source": "wfdb" if self.local_dir else "physionet", "kind": "signals",
                "pn_dir": self.pn_dir,
                "records": len(recs), "record_ids": recs[:500], "fs": first.get("fs"),
                "channels": first.get("channels"), "units": first.get("units"),
                "record_seconds": first.get("seconds"), "annotation_ext": self._ann_ext,
                "header_comments_example": first.get("comments"),
                "labels": dict(sorted(labels.items(), key=lambda x: -x[1])[:40]),
                "labels_sampled_from": min(len(recs), max_records),
                "record_labels": per_record}

    def window(self, record: str, start: float, dur: float,
               channels: list[str] | None = None) -> dict:
        h = self.header(record)
        if not h["channels"] or not h["seconds"]:
            raise SourceError(f"record {record} has no signal (annotations only)")
        fs = h["fs"]
        start = max(0.0, float(start))
        dur = max(0.5, min(float(dur), 600.0))
        a, b = int(start * fs), int(min(h["seconds"], start + dur) * fs)
        try:
            name, pn = self._split(record)
            rec = self._wfdb().rdrecord(name, pn_dir=pn, sampfrom=a, sampto=max(a + 1, b))
        except Exception as exc:
            raise SourceError(f"read {record}: {exc}") from exc
        names = list(rec.sig_name)
        want = [c for c in (channels or names) if c in names] or names
        sig = rec.p_signal
        out = [{"name": c, "unit": (rec.units or [""] * len(names))[names.index(c)],
                "values": downsample([row[names.index(c)] for row in sig])} for c in want]
        anns = [x for x in self.annotations(record) if start <= x["t"] <= start + dur]
        return {"record": record, "fs": fs, "start": start, "dur": (b - a) / fs,
                "record_seconds": h["seconds"], "channels": out, "annotations": anns[:2000]}

    def traces(self, channel: str | None, label: str | None, n: int, window: float,
               align: str = "event", points: int = 300) -> dict:
        """Up to n windows of one channel, from records carrying `label`
        (aligned at that label's first annotation, or the record start)."""
        recs = self.records()
        traces, used = [], []
        for r in recs:
            if len(traces) >= n:
                break
            anns = self.annotations(r)
            t0 = 0.0
            if label:
                hits = [a["t"] for a in anns if a["label"] == label]
                if not hits:
                    continue
                t0 = max(0.0, hits[0] - (window / 4 if align == "event" else 0)) \
                    if align == "event" else 0.0
            try:
                w = self.window(r, t0, window, [channel] if channel else None)
            except SourceError:
                continue
            if not w["channels"]:
                continue
            traces.append(resample(w["channels"][0]["values"], points))
            used.append(r)
        return {"traces": traces, "ids": used, "pooled": pooled(traces),
                "seconds": window, "points": points}


# ------------------------------------------------------------------ files
class FilesSource:
    """Files on our volume (previously downloaded, or acquired for Explore):
    image folders, tables, and zips of either."""

    def __init__(self, paths: list[Path]):
        self.paths = [p for p in paths if p.exists()]
        self._members: list[tuple[str, str]] | None = None   # (container path, member)
        self._table = None
        self._table_name: str | None = None

    # -- inventory
    def members(self) -> list[tuple[str, str]]:
        if self._members is not None:
            return self._members
        out = []
        for p in self.paths:
            if p.suffix.lower() == ".zip":
                try:
                    with zipfile.ZipFile(p) as z:
                        out += [(str(p), m) for m in z.namelist() if not m.endswith("/")
                                and "__MACOSX" not in m]
                except zipfile.BadZipFile:
                    continue
            elif p.is_dir():
                out += [(str(f), "") for f in p.rglob("*") if f.is_file()]
            else:
                out.append((str(p), ""))
        self._members = out
        return out

    @staticmethod
    def _name(m: tuple[str, str]) -> str:
        return m[1] or m[0]

    def images(self) -> list[tuple[str, str]]:
        return [m for m in self.members() if self._name(m).lower().endswith(IMAGE_EXT)]

    def tables(self) -> list[tuple[str, str]]:
        return [m for m in self.members() if self._name(m).lower().endswith(TABLE_EXT)]

    def signal_files(self) -> list[tuple[str, str]]:
        """Text files that each hold one recording: a single row or column of
        numbers (e.g. PPG-BP's 657 `100_1.txt` files). Labels for them come
        from a metadata table joined on the file name."""
        if getattr(self, "_signal_files", None) is not None:
            return self._signal_files
        out = []
        for m in self.tables():
            if not self._name(m).lower().endswith((".txt", ".csv", ".tsv")):
                continue
            try:
                head = self.read_bytes(m)[:4096].decode("utf-8", "ignore")
            except Exception:
                continue
            lines = [ln for ln in head.splitlines() if ln.strip()]
            toks = [t for ln in lines for t in re.split(r"[\s,;]+", ln.strip()) if t]
            if len(toks) >= 50 and all(_NUM_TOKEN.match(t) for t in toks[:400]) and (
                    len(lines) <= 2 or all(len(re.split(r"[\s,;]+", ln.strip())) == 1
                                            for ln in lines[:50])):
                out.append(m)
        self._signal_files = out if len(out) >= 10 else []
        return self._signal_files

    @property
    def kind(self) -> str:
        imgs, tabs = self.images(), self.tables()
        if (len(imgs) >= 20 and len(imgs) >= len(tabs)) or (len(imgs) >= 5 and len(imgs) > 3 * len(tabs)):
            return "images"
        if self.signal_files():
            return "signals"
        return "table" if tabs else ("images" if imgs else "none")

    def has_table(self) -> bool:
        sig = set(self.signal_files())
        return any(m not in sig for m in self.tables())

    def read_bytes(self, m: tuple[str, str]) -> bytes:
        if m[1]:
            with zipfile.ZipFile(m[0]) as z:
                return z.read(m[1])
        return Path(m[0]).read_bytes()

    # -- images (label = parent folder, plus any metadata table joined on name)
    def image_join(self) -> dict | None:
        """A metadata table column holding image file stems, if there is one."""
        if getattr(self, "_img_join", 0) != 0:
            return self._img_join
        self._img_join = None
        if self.has_table():
            stems = {self._stem(m) for m in self.images()}
            df = self.table()
            for c in df.columns:
                vals = set(df[c].astype(str))
                hits = len(stems & vals)
                if hits >= max(3, len(stems) // 3):
                    cols = [x for x in df.columns if x != c and 1 < df[x].nunique(dropna=False) <= 40]
                    rows = {str(k): r for k, r in zip(df[c].astype(str), df.to_dict("records"))}
                    self._img_join = {"key": c, "columns": cols, "rows": rows, "matched": hits}
                    break
        return self._img_join

    def image_index(self) -> list[dict]:
        if getattr(self, "_img_index", None) is not None:
            return self._img_index
        join = self.image_join()
        out = []
        for i, m in enumerate(self.images()):
            parts = self._name(m).replace("\\", "/").split("/")
            label = parts[-2] if len(parts) >= 2 else ""
            row = {"index": i, "label": label, "name": parts[-1],
                   "split": next((p for p in parts[:-1] if p.lower() in
                                  ("train", "test", "val", "valid", "validation")), "")}
            if join:
                meta = join["rows"].get(self._stem(m)) or {}
                for c in join["columns"]:
                    v = meta.get(c)
                    row[c] = None if v is None or v != v else (int(v) if isinstance(v, float) and v.is_integer() else v)
            out.append(row)
        self._img_index = out
        return out

    def image_rows(self, where: dict | None, offset: int, length: int, file_url) -> dict:
        idx = self.image_index()
        if where:
            norm = lambda v: "(blank)" if v is None or v == "" else str(v)  # noqa: E731
            idx = [r for r in idx if all(norm(r.get(k)) == str(v) for k, v in where.items())]
        page = idx[offset: offset + length]
        return {"rows": [{**r, "image": file_url(r["index"])} for r in page], "total": len(idx)}

    # -- tables
    def table(self):
        if self._table is not None:
            return self._table
        import pandas as pd
        sig = set(self.signal_files())
        tabs = [m for m in self.tables() if m not in sig]
        if not tabs:
            raise SourceError("no table files")
        # Spreadsheets first (usually the labels/metadata), then the largest
        # text table (usually the data, not a README-ish txt).
        sizes = []
        for m in tabs:
            try:
                n = len(self.read_bytes(m))
            except Exception:
                continue
            xl = self._name(m).lower().endswith((".xlsx", ".xls"))
            sizes.append(((xl, n), m))
        _, m = max(sizes, key=lambda x: x[0])
        raw = self.read_bytes(m)
        name = self._name(m).lower()
        if name.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(raw), header=None, nrows=TABLE_MAX_ROWS)
        else:
            sep = "\t" if name.endswith(".tsv") else None
            df = pd.read_csv(io.BytesIO(raw), sep=sep, engine="python", nrows=TABLE_MAX_ROWS,
                             on_bad_lines="skip", header=None)
            if df.shape[1] == 1 and name.endswith(".txt"):   # whitespace-delimited
                df = pd.read_csv(io.BytesIO(raw), sep=r"\s+", engine="python", header=None,
                                 nrows=TABLE_MAX_ROWS)
        df = _with_header(df)
        self._table, self._table_name = df, self._name(m)
        return df

    def table_probe(self) -> dict:
        df = self.table()
        cols = []
        for c in df.columns[:80]:
            s = df[c]
            num = s.dtype.kind in "if"
            info = {"name": c, "kind": "number" if num else "text",
                    "missing": round(float(s.isna().mean()), 3), "unique": int(s.nunique())}
            if num:
                info.update(min=_f(s.min()), max=_f(s.max()), mean=_f(s.mean()))
            else:
                info["top"] = {str(k): int(v) for k, v in s.value_counts().head(8).items()}
            cols.append(info)
        return {"table": self._table_name, "rows": int(df.shape[0]), "columns": cols,
                "sample": json.loads(df.head(5).to_json(orient="records"))}

    def probe(self) -> dict:
        kind = self.kind
        base = {"source": "files", "kind": kind, "files": len(self.members())}
        if kind == "images":
            idx = self.image_index()
            labels: dict[str, int] = {}
            for r in idx:
                labels[r["label"]] = labels.get(r["label"], 0) + 1
            fields = [{"name": "image", "kind": "image"}]
            if len(labels) > 1:
                fields.append({"name": "label", "kind": "class_label"})
            if any(r["split"] for r in idx):
                fields.append({"name": "split", "kind": "class_label"})
            stats = {}
            join = self.image_join()
            for c in (join or {}).get("columns", []):
                counts: dict[str, int] = {}
                for r in idx:
                    k = "(blank)" if r.get(c) is None else str(r[c])
                    counts[k] = counts.get(k, 0) + 1
                fields.append({"name": c, "kind": "class_label"})
                stats[c] = {"frequencies": dict(sorted(counts.items(), key=lambda x: -x[1])[:40])}
            base.update(images=len(idx), labels=dict(sorted(labels.items(), key=lambda x: -x[1])[:60]),
                        fields=fields, stats=stats,
                        metadata_join={"key": join["key"], "matched": join["matched"]} if join else None)
        elif kind == "table":
            base.update(self.table_probe())
        elif kind == "signals":
            files = self.signal_files()
            first = self.vector(files[0])
            base.update(records=len(files), record_ids=[self._stem(m) for m in files[:500]],
                        channels=["signal"], fs=None, samples_per_record=len(first),
                        value_range=[_f(min(first)), _f(max(first))])
            if self.has_table():
                base["meta"] = self.table_probe()
                join = self.guess_join()
                if join:
                    base["join"] = join
                    base["labels"] = self.label_counts(join["id_col"], join["label_col"]) \
                        if join.get("label_col") else {}
        return base

    # -- one recording per file, labels from a metadata table
    @staticmethod
    def _stem(m: tuple[str, str]) -> str:
        return re.sub(r"\.[^.]+$", "", (m[1] or m[0]).replace("\\", "/").split("/")[-1])

    @staticmethod
    def _key(stem: str) -> str:
        """Subject key in a file name: `100_1` -> `100`, `s07-run2` -> `s07`."""
        return re.split(r"[_\-. ]", stem)[0].lstrip("0") or "0"

    def vector(self, m: tuple[str, str]) -> list[float]:
        txt = self.read_bytes(m).decode("utf-8", "ignore")
        return [float(t) for t in re.split(r"[\s,;]+", txt.strip()) if _NUM_TOKEN.match(t)]

    def guess_join(self) -> dict | None:
        """Which metadata column holds the file-name key, and a label column."""
        df = self.table()
        keys = {self._key(self._stem(m)) for m in self.signal_files()}
        best, hits = None, 0
        for c in df.columns:
            vals = {str(v).split(".")[0].lstrip("0") or "0" for v in df[c].dropna()}
            n = len(keys & vals)
            if n > hits:
                best, hits = c, n
        if not best or hits < max(3, len(keys) // 4):
            return None
        cats = [c for c in df.columns if c != best and df[c].dtype.kind not in "if"
                and 1 < df[c].nunique() <= 12]
        pref = [c for c in cats if re.search(r"hypertension|class|label|diagnos|disease|group|status|grade|stage", str(c), re.I)]
        return {"id_col": best, "matched_keys": hits, "label_col": (pref or cats or [None])[0],
                "label_candidates": cats[:8]}

    def _meta_index(self, id_col: str) -> dict[str, Any]:
        df = self.table()
        return {(str(v).split(".")[0].lstrip("0") or "0"): row for v, row in
                zip(df[id_col], df.to_dict("records")) if v == v}

    def label_counts(self, id_col: str, label_col: str) -> dict[str, int]:
        meta = self._meta_index(id_col)
        out: dict[str, int] = {}
        for m in self.signal_files():
            row = meta.get(self._key(self._stem(m)))
            lab = str(row.get(label_col)) if row and row.get(label_col) == row.get(label_col) else "(none)"
            out[lab] = out.get(lab, 0) + 1
        return dict(sorted(out.items(), key=lambda x: -x[1]))

    def file_records(self, cfg: dict | None) -> list[dict]:
        cfg = cfg or {}
        meta = self._meta_index(cfg["id_col"]) if cfg.get("id_col") and self.has_table() else {}
        lab = cfg.get("label_col")
        out = []
        for m in self.signal_files():
            stem = self._stem(m)
            row = meta.get(self._key(stem)) or {}
            v = row.get(lab) if lab else None
            out.append({"id": stem, "labels": [str(v)] if v is not None and v == v else []})
        return out

    def _file(self, stem: str) -> tuple[str, str]:
        for m in self.signal_files():
            if self._stem(m) == stem:
                return m
        raise SourceError(f"no record {stem}")

    def file_window(self, cfg: dict | None, record: str, start: float, dur: float) -> dict:
        fs = float((cfg or {}).get("fs") or 1)
        vals = self.vector(self._file(record))
        a, b = int(max(0, start) * fs), int((max(0, start) + dur) * fs)
        return {"record": record, "fs": (cfg or {}).get("fs"), "start": a / fs, "dur": (min(b, len(vals)) - a) / fs,
                "record_seconds": round(len(vals) / fs, 3),
                "channels": [{"name": "signal", "unit": "", "values": downsample(vals[a:b])}],
                "annotations": []}

    def file_traces(self, cfg: dict | None, label: str | None, n: int, window: float | None,
                    points: int = 300) -> dict:
        fs = float((cfg or {}).get("fs") or 1)
        traces, used = [], []
        for r in self.file_records(cfg):
            if len(traces) >= n:
                break
            if label and label not in r["labels"]:
                continue
            vals = self.vector(self._file(r["id"]))
            if window:
                vals = vals[: int(window * fs)]
            traces.append(resample(vals, points))
            used.append(r["id"])
        return {"traces": traces, "ids": used, "pooled": pooled(traces),
                "seconds": round(len(vals) / fs, 3) if traces else window, "points": points}

    def table_rows(self, where: dict | None, offset: int, length: int,
                   columns: list[str] | None = None) -> dict:
        df = self.table()
        if where:
            for k, v in where.items():
                if k in df.columns:
                    df = df[df[k].astype(str) == str(v)]
        if columns:
            df = df[[c for c in columns if c in df.columns]]
        page = df.iloc[offset: offset + length]
        return {"rows": json.loads(page.to_json(orient="records")), "total": int(len(df)),
                "columns": list(df.columns)}

    def distribution(self, field: str, group_by: str | None = None, bins: int = 20) -> dict:
        df = self.table()
        if field not in df.columns:
            raise SourceError(f"no column {field}")
        s = df[field]
        groups = ([(str(g), sub[field]) for g, sub in df.groupby(group_by)][:12]
                  if group_by and group_by in df.columns else [("all", s)])
        if s.dtype.kind in "if":
            lo, hi = _f(s.min()), _f(s.max())
            edges = [lo + (hi - lo) * i / bins for i in range(bins + 1)] if hi > lo else [lo, lo + 1]
            out = []
            for g, sub in groups:
                counts = [0] * (len(edges) - 1)
                for v in sub.dropna():
                    j = min(len(counts) - 1, int((v - edges[0]) / ((edges[-1] - edges[0]) or 1) * len(counts)))
                    counts[j] += 1
                out.append({"group": g, "counts": counts, "n": int(sub.notna().sum())})
            return {"type": "histogram", "edges": [round(e, 5) for e in edges], "groups": out}
        out = []
        for g, sub in groups:
            out.append({"group": g, "counts": {str(k): int(v) for k, v in
                                               sub.value_counts().head(30).items()}})
        return {"type": "categorical", "groups": out}

    def group_summary(self, fields: list[str], group_by: str) -> dict:
        df = self.table()
        if group_by not in df.columns:
            raise SourceError(f"no column {group_by}")
        fields = [f for f in fields if f in df.columns and df[f].dtype.kind in "if"][:12]
        rows = []
        for g, sub in list(df.groupby(group_by))[:40]:
            row = {"group": str(g), "n": int(len(sub))}
            for f in fields:
                row[f] = {"mean": _f(sub[f].mean()), "sd": _f(sub[f].std())}
            rows.append(row)
        return {"group_by": group_by, "fields": fields, "rows": rows}

    # -- tables read as series (IMU / sensor CSVs)
    def series_records(self, id_col: str, label_col: str | None) -> list[dict]:
        df = self.table()
        if id_col not in df.columns:
            raise SourceError(f"no column {id_col}")
        out = []
        for rid, sub in list(df.groupby(id_col))[:2000]:
            labels = sorted(sub[label_col].dropna().astype(str).unique().tolist())[:10] \
                if label_col and label_col in df.columns else []
            out.append({"id": str(rid), "labels": labels, "n": int(len(sub))})
        return out

    def series_window(self, cfg: dict, record: str, start: float, dur: float,
                      channels: list[str] | None = None) -> dict:
        df = self.table()
        sub = df[df[cfg["id_col"]].astype(str) == str(record)]
        tcol = cfg.get("time_col")
        if tcol and tcol in sub.columns:
            sub = sub.sort_values(tcol)
            t = (sub[tcol] - sub[tcol].iloc[0]).astype(float)
            fs = None
        else:
            fs = float(cfg.get("fs") or 1)
            t = sub.reset_index(drop=True).index / fs
        sub = sub.assign(_t=list(t))
        win = sub[(sub["_t"] >= start) & (sub["_t"] <= start + dur)]
        chans = [c for c in (channels or cfg.get("channels") or []) if c in df.columns]
        anns = []
        lab = cfg.get("label_col")
        if lab and lab in win.columns:   # label changes become annotations
            prev = None
            for tt, v in zip(win["_t"], win[lab].astype(str)):
                if v != prev:
                    anns.append({"t": round(float(tt), 3), "label": v, "symbol": ""})
                    prev = v
        return {"record": record, "fs": fs, "start": start, "dur": dur,
                "record_seconds": round(float(sub["_t"].max()) if len(sub) else 0, 2),
                "channels": [{"name": c, "unit": "", "values": downsample(win[c].tolist())}
                             for c in chans],
                "annotations": anns[:2000]}

    def series_traces(self, cfg: dict, channel: str, label: str | None, n: int,
                      window: float | None, points: int = 300) -> dict:
        df = self.table()
        idc, lab = cfg["id_col"], cfg.get("label_col")
        traces, used = [], []
        for rid, sub in df.groupby(idc):
            if len(traces) >= n:
                break
            if label and lab in df.columns:
                sub = sub[sub[lab].astype(str) == str(label)]
                if sub.empty:
                    continue
            if channel not in sub.columns:
                continue
            tcol = cfg.get("time_col")
            if tcol and tcol in sub.columns:
                sub = sub.sort_values(tcol)
                if window:
                    t = sub[tcol] - sub[tcol].iloc[0]
                    sub = sub[t <= window]
            elif window and cfg.get("fs"):
                sub = sub.iloc[: int(window * float(cfg["fs"]))]
            traces.append(resample(sub[channel].tolist(), points))
            used.append(str(rid))
        return {"traces": traces, "ids": used, "pooled": pooled(traces),
                "seconds": window, "points": points}


def _with_header(df):
    """Use the first row that looks like a header (mostly text, few blanks),
    skipping title rows above it; numbered columns when there is none."""
    head = None
    for i in range(min(6, len(df))):
        row = df.iloc[i]
        filled = row.notna().mean()
        texty = sum(isinstance(v, str) and not _NUM_TOKEN.match(v.strip()) for v in row) / max(1, len(row))
        if filled >= 0.6 and texty >= 0.6:
            head = i
            break
    if head is None:
        df.columns = [f"col{i}" for i in range(df.shape[1])]
        return df
    cols, seen = [], {}
    for j, c in enumerate(df.iloc[head]):
        name = str(c).replace("\ufeff", "").strip() if c == c and str(c).strip() else f"col{j}"
        seen[name] = seen.get(name, 0) + 1
        cols.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    out = df.iloc[head + 1:].reset_index(drop=True)
    out.columns = cols
    return out.apply(lambda s: _numeric(s))


def _numeric(s):
    import pandas as pd
    conv = pd.to_numeric(s, errors="coerce")
    return conv if conv.notna().sum() >= 0.8 * s.notna().sum() and s.notna().any() else s


def _f(v) -> float | None:
    try:
        v = float(v)
        return None if math.isnan(v) else round(v, 5)
    except (TypeError, ValueError):
        return None


def file_url(ds_id: str, i: int) -> str:
    return f"/api/explore/{quote(ds_id)}/file/{i}"
