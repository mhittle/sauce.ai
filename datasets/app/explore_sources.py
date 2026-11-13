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
TABLE_EXT = (".csv", ".tsv", ".txt")


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
            body = self._get("filter", config=self.config, split=self.split,
                             where=" AND ".join(clauses), offset=offset, length=length)
        else:
            body = self._get("rows", config=self.config, split=self.split,
                             offset=offset, length=length)
        out = []
        for r in body.get("rows", []):
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
        return {"rows": out, "total": body.get("num_rows_total")}


# ------------------------------------------------------------------ PhysioNet WFDB
class WFDBSource:
    """An open PhysioNet WFDB database, streamed record by record."""

    kind = "signals"
    ANN_EXTS = ("atr", "qrs", "apn", "ecg", "arousal", "st", "event", "ann", "pwave")

    def __init__(self, pn_dir: str):
        self.pn_dir = pn_dir
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
            try:
                a = wfdb.rdann(record, ext, pn_dir=self.pn_dir)
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

    def header(self, record: str) -> dict:
        cache = self.__dict__.setdefault("_hdr", {})
        if record in cache:
            return cache[record]
        try:
            h = self._wfdb().rdheader(record, pn_dir=self.pn_dir)
        except Exception as exc:
            raise SourceError(f"header {record}: {exc}") from exc
        cache[record] = {"fs": float(h.fs), "channels": list(h.sig_name or []),
                         "units": list(h.units or []),
                         "seconds": round((h.sig_len or 0) / float(h.fs), 1)}
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
        return {"source": "physionet", "kind": "signals", "pn_dir": self.pn_dir,
                "records": len(recs), "record_ids": recs[:500], "fs": first.get("fs"),
                "channels": first.get("channels"), "units": first.get("units"),
                "record_seconds": first.get("seconds"), "annotation_ext": self._ann_ext,
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
            rec = self._wfdb().rdrecord(record, pn_dir=self.pn_dir, sampfrom=a, sampto=max(a + 1, b))
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

    @property
    def kind(self) -> str:
        imgs, tabs = self.images(), self.tables()
        if len(imgs) >= 20 and len(imgs) >= len(tabs):
            return "images"
        return "table" if tabs else ("images" if imgs else "none")

    def read_bytes(self, m: tuple[str, str]) -> bytes:
        if m[1]:
            with zipfile.ZipFile(m[0]) as z:
                return z.read(m[1])
        return Path(m[0]).read_bytes()

    # -- images (label = parent folder)
    def image_index(self) -> list[dict]:
        out = []
        for i, m in enumerate(self.images()):
            parts = self._name(m).replace("\\", "/").split("/")
            label = parts[-2] if len(parts) >= 2 else ""
            out.append({"index": i, "label": label, "name": parts[-1],
                        "split": next((p for p in parts[:-1] if p.lower() in
                                       ("train", "test", "val", "valid", "validation")), "")})
        return out

    def image_rows(self, where: dict | None, offset: int, length: int, file_url) -> dict:
        idx = self.image_index()
        if where:
            idx = [r for r in idx if all(str(r.get(k)) == str(v) for k, v in where.items())]
        page = idx[offset: offset + length]
        return {"rows": [{**r, "image": file_url(r["index"])} for r in page], "total": len(idx)}

    # -- tables
    def table(self):
        if self._table is not None:
            return self._table
        import pandas as pd
        tabs = self.tables()
        if not tabs:
            raise SourceError("no table files")
        # Largest table first (usually the data, not a README-ish txt).
        sizes = []
        for m in tabs:
            try:
                sizes.append((len(self.read_bytes(m)), m))
            except Exception:
                continue
        _, m = max(sizes, key=lambda x: x[0])
        raw = self.read_bytes(m)
        name = self._name(m).lower()
        sep = "\t" if name.endswith(".tsv") else None
        df = pd.read_csv(io.BytesIO(raw), sep=sep, engine="python", nrows=TABLE_MAX_ROWS,
                         on_bad_lines="skip")
        if df.shape[1] == 1 and name.endswith(".txt"):   # whitespace-delimited
            df = pd.read_csv(io.BytesIO(raw), sep=r"\s+", engine="python", header=None,
                             nrows=TABLE_MAX_ROWS)
            df.columns = [f"col{i}" for i in range(df.shape[1])]
        df.columns = [str(c).strip() for c in df.columns]
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
            base.update(images=len(idx), labels=dict(sorted(labels.items(), key=lambda x: -x[1])[:60]),
                        fields=[{"name": "label", "kind": "class_label"},
                                {"name": "split", "kind": "class_label"}])
        elif kind == "table":
            base.update(self.table_probe())
        return base

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


def _f(v) -> float | None:
    try:
        v = float(v)
        return None if math.isnan(v) else round(v, 5)
    except (TypeError, ValueError):
        return None


def file_url(ds_id: str, i: int) -> str:
    return f"/api/explore/{quote(ds_id)}/file/{i}"
