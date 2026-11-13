"""Explore: a per-dataset data-exploration page for hypothesis generation.

Each dataset gets its own explore *spec*: an ordered list of views chosen from
a fixed template library and configured for that dataset's actual fields and
labels. The library keeps every explore page consistent; the spec makes each
one specific (a chest X-ray set opens an image gallery grouped by finding with
mask overlays; an IMU set opens pooled and individual "spaghetti" traces per
activity).

Lifecycle (background job, :class:`ExploreManager`):

1. **Acquire** a sample: a built-in source if one fits (Hugging Face
   datasets-server, open PhysioNet WFDB), else files already on the volume,
   else the card's direct download links, else (open datasets, with an API
   key) a short Claude agent that searches the web for direct file links and
   verifies them. Files land under ``<data>/explore/<id>/`` (size-capped,
   independent of DATASETS_DOWNLOAD). Datasets behind credentials or DUAs
   stop here with their access steps.
2. **Probe** the source (fields, labels, channels, sizes).
3. **Compose** the spec: Claude picks and configures views from the library
   (a heuristic without a key). Specs are stored with version history.

Edits: the page's prompt box sends a request; Claude rewrites the spec within
the library. A request for a view the library lacks is answered and logged
as a tool request (``explore_requests``) rather than improvised — specs are
data, never code, so a public page can't be made to run arbitrary scripts.
Set DATASETS_EDIT_TOKEN to restrict building and editing.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Any

from . import download
from .config import Settings
from .explore_sources import (FilesSource, HFSource, SourceError, WFDBSource)
from .store import Store, now_iso

log = logging.getLogger(__name__)

VIEW_TYPES = {
    "image_gallery": "Images grouped by a label field; click one to open a viewer with zoom, "
                     "pan, and mask overlay (opacity slider). params: image_field, mask_field, "
                     "group_by, per_group.",
    "label_distribution": "Bar chart of counts per value of a label/categorical field. "
                          "params: field.",
    "histogram": "Distribution of a numeric field, optionally split by a group. params: field, "
                 "group_by, bins.",
    "signal_viewer": "One record's channels over time with annotation markers; record picker "
                     "filterable by label; pan/zoom in time. params: channels, window_sec.",
    "spaghetti": "Many records' traces of one channel overlaid (thin lines) with the pooled "
                 "mean ± SD, one panel per label. params: channel, labels, n_per_group, "
                 "window_sec, align ('event' = centered on the label's first annotation, "
                 "'start').",
    "group_summary": "Table of mean ± SD of numeric fields per group. params: fields, group_by.",
    "record_table": "Paged rows of the table. params: columns.",
    "notes": "Markdown text: what the data contain, caveats, and hypotheses to test with "
             "the views above. params: text.",
}
_NULLABLE = {"type": ["string", "null"]}
PANEL = {
    "type": "object", "additionalProperties": False,
    "required": ["type", "title", "description", "params"],
    "properties": {
        "type": {"type": "string", "enum": list(VIEW_TYPES)},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "params": {
            "type": "object", "additionalProperties": False,
            "required": ["field", "group_by", "image_field", "mask_field", "per_group",
                         "channels", "channel", "labels", "n_per_group", "window_sec",
                         "align", "bins", "fields", "columns", "text"],
            "properties": {
                "field": _NULLABLE, "group_by": _NULLABLE, "image_field": _NULLABLE,
                "mask_field": _NULLABLE, "per_group": {"type": ["integer", "null"]},
                "channels": {"type": ["array", "null"], "items": {"type": "string"}},
                "channel": _NULLABLE,
                "labels": {"type": ["array", "null"], "items": {"type": "string"}},
                "n_per_group": {"type": ["integer", "null"]},
                "window_sec": {"type": ["number", "null"]},
                "align": {"type": ["string", "null"], "enum": ["event", "start", None]},
                "bins": {"type": ["integer", "null"]},
                "fields": {"type": ["array", "null"], "items": {"type": "string"}},
                "columns": {"type": ["array", "null"], "items": {"type": "string"}},
                "text": _NULLABLE,
            },
        },
    },
}
SPEC_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["title", "summary", "series", "panels", "reply", "tool_requests"],
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "series": {"type": ["object", "null"], "additionalProperties": False,
                   "required": ["id_col", "time_col", "label_col", "channels", "fs"],
                   "properties": {"id_col": {"type": "string"}, "time_col": _NULLABLE,
                                  "label_col": _NULLABLE,
                                  "channels": {"type": "array", "items": {"type": "string"}},
                                  "fs": {"type": ["number", "null"]}}},
        "panels": {"type": "array", "items": PANEL},
        "reply": {"type": "string"},
        "tool_requests": {"type": "array", "items": {"type": "string"}},
    },
}

COMPOSE_SYSTEM = """You design data-exploration pages for medical datasets, used by \
researchers to look at the data and generate hypotheses before modeling.

You get the dataset card and a probe of the actual data (fields, label values with \
counts, channels, sampling rate, table columns). Compose an explore page from these \
views only, configured with names that exist in the probe:

{views}

Guidelines:
- Lead with the view that shows the data itself (image_gallery for images, \
signal_viewer / spaghetti for signals and sensor series, record_table for tables), \
then distributions, then comparisons between labels.
- Images: group_by the main label; set mask_field when a mask/segmentation image \
field exists.
- Tables that hold time series (one row per sample, with a subject/trial/record id and \
sensor channels, e.g. IMU accelerometer x/y/z): set `series` (id_col, time_col if \
any, label_col, channels, fs if known) and use signal_viewer and spaghetti.
- spaghetti: pick 2-6 labels worth contrasting; n_per_group 10-30.
- End with a notes view: 3-6 concrete, testable hypotheses the views can probe, and \
caveats (class imbalance, label noise, small n).
- Unused params are null. Keep titles short.

When the user asks for a change, return the full revised spec and say what changed \
in `reply`. If they ask for something no view can do, keep the spec, explain in \
`reply`, and add a one-line description of the needed view to `tool_requests`."""


def heuristic_spec(probe: dict) -> dict:
    """A sensible default page per data kind (used without an API key)."""
    p = lambda **kw: {k: kw.get(k) for k in PANEL["properties"]["params"]["required"]}  # noqa: E731
    panels = []
    spec_series = None
    kind = probe.get("kind")
    if kind == "images":
        fields = probe.get("fields", [])
        img = next((f["name"] for f in fields if f["kind"] == "image"), "image")
        mask = next((f["name"] for f in fields if f["kind"] == "image" and f["name"] != img), None)
        label = next((f["name"] for f in fields if f["kind"] in ("class_label", "label_number")),
                     None)
        panels.append({"type": "image_gallery", "title": "Images by label",
                       "description": "", "params": p(image_field=img, mask_field=mask,
                                                      group_by=label, per_group=12)})
        if label:
            panels.append({"type": "label_distribution", "title": "Label counts",
                           "description": "", "params": p(field=label)})
    elif kind == "signals":
        labels = list((probe.get("labels") or {}).keys())[:4]
        chans = (probe.get("channels") or [])[:4]
        panels.append({"type": "signal_viewer", "title": "Recordings", "description": "",
                       "params": p(channels=chans, window_sec=10)})
        if labels and chans:
            panels.append({"type": "spaghetti", "title": f"{chans[0]} by label",
                           "description": "", "params": p(channel=chans[0], labels=labels,
                                                          n_per_group=8, window_sec=10,
                                                          align="event")})
    elif kind == "table":
        cols = probe.get("columns", [])
        cats = [c["name"] for c in cols if c["kind"] == "text" and 1 < c["unique"] <= 20]
        nums = [c["name"] for c in cols if c["kind"] == "number"]
        idc = next((c["name"] for c in cols if re.search(r"(subject|participant|patient|trial|record|session)(_?id)?$|^id$", c["name"], re.I)), None)
        tcol = next((c["name"] for c in cols if re.search(r"^(time|timestamp|t|seconds|ms)$|time", c["name"], re.I) and c["kind"] == "number"), None)
        chans = [n for n in nums if n not in (idc, tcol)][:6]
        rows_per_id = probe.get("rows", 0) / max(1, next((c["unique"] for c in cols if c["name"] == idc), 1))
        if idc and len(chans) >= 2 and rows_per_id >= 20:   # long format: a sensor series per id
            series = {"id_col": idc, "time_col": tcol, "label_col": cats[0] if cats else None,
                      "channels": chans, "fs": None}
            panels.append({"type": "signal_viewer", "title": "Recordings", "description": "",
                           "params": p(channels=chans[:4], window_sec=30)})
            panels.append({"type": "spaghetti", "title": f"{chans[0]} by {cats[0]}" if cats else chans[0],
                           "description": "", "params": p(channel=chans[0], labels=None,
                                                          n_per_group=15, window_sec=None,
                                                          align="start")})
            spec_series = series
        panels.append({"type": "record_table", "title": "Rows", "description": "",
                       "params": p(columns=[c["name"] for c in cols[:12]])})
        if cats:
            panels.append({"type": "label_distribution", "title": f"{cats[0]} counts",
                           "description": "", "params": p(field=cats[0])})
        idish = re.compile(r"(^|_)(id|index|idx)$|^(time|timestamp|t|seconds|ms)$|time", re.I)
        for n in [x for x in nums if not idish.search(x)][:3]:
            panels.append({"type": "histogram", "title": n, "description": "",
                           "params": p(field=n, group_by=cats[0] if cats else None, bins=20)})
        if cats and nums:
            panels.append({"type": "group_summary", "title": f"By {cats[0]}", "description": "",
                           "params": p(fields=nums[:8], group_by=cats[0])})
    return {"title": "Explore", "summary": "Default views (no Claude key configured).",
            "series": spec_series, "panels": panels, "reply": "",
            "tool_requests": []}


def _probe_for_prompt(probe: dict) -> str:
    slim = {k: v for k, v in probe.items() if k not in ("record_ids", "record_labels", "sample")}
    if "sample" in probe:
        slim["sample_rows"] = probe["sample"][:3]
    return json.dumps(slim, default=str)[:12000]


def compose_llm(client, settings: Settings, ds: dict, probe: dict, current: dict | None = None,
                request: str | None = None) -> dict:
    from .crawler import _create
    card = {k: ds.get(k) for k in ("title", "source", "description", "labels", "conditions",
                                   "modalities", "n_subjects")}
    msg = f"Dataset card:\n{json.dumps(card, default=str)}\n\nData probe:\n{_probe_for_prompt(probe)}"
    if current is not None:
        msg += (f"\n\nCurrent spec:\n{json.dumps(current)}\n\nUser request:\n{request}")
    resp = _create(client, settings,
                   system=COMPOSE_SYSTEM.format(views="\n".join(f"- {k}: {v}" for k, v in VIEW_TYPES.items())),
                   output_config={"effort": "medium",
                                  "format": {"type": "json_schema", "schema": SPEC_SCHEMA}},
                   messages=[{"role": "user", "content": msg}])
    if resp.stop_reason == "refusal":
        raise RuntimeError("request declined")
    return json.loads(next(b.text for b in resp.content if b.type == "text"))


def validate_spec(spec: dict, probe: dict) -> dict:
    """Drop views that reference fields/channels the data doesn't have."""
    names: set[str] = set()
    names |= {f["name"] for f in probe.get("fields", [])}
    names |= {c["name"] for c in probe.get("columns", [])}
    names |= set(probe.get("channels") or [])
    keep, dropped = [], []
    for panel in spec.get("panels", []):
        prm = panel.get("params") or {}
        refs = [prm.get(k) for k in ("field", "group_by", "image_field", "mask_field", "channel")]
        refs += list(prm.get("channels") or []) + list(prm.get("fields") or []) + \
            list(prm.get("columns") or [])
        bad = [r for r in refs if r and names and r not in names]
        if bad and panel["type"] != "notes":
            dropped.append(f"{panel['title']} (unknown: {', '.join(bad[:3])})")
            continue
        keep.append(panel)
    spec["panels"] = keep
    if dropped:
        spec["reply"] = (spec.get("reply") or "") + f" Dropped views referring to missing data: {'; '.join(dropped)}."
    return spec


# ------------------------------------------------------------------ acquisition
FIND_FILES_TOOL = {
    "name": "report_files",
    "description": "Report direct download URLs of data files for this dataset (CSV/TSV/TXT, "
                   "ZIP of images or tables, EDF, NIfTI). Verify each with probe_url first; "
                   "prefer a small sample or subset (<300 MB) over the full release.",
    "input_schema": {"type": "object", "properties": {
        "urls": {"type": "array", "items": {"type": "string"}},
        "note": {"type": "string"}}, "required": ["urls"]},
}
FIND_SYSTEM = """You find direct, unauthenticated download links for an open medical \
dataset so a sample can be explored. Use web_search / web_fetch to locate the files \
(repository file listings, GitHub releases, Zenodo/Figshare/Mendeley/OSF records), \
check candidates with probe_url (must be a file, not an HTML page or login), then \
call report_files once with up to 5 URLs, smallest useful sample first. If the data \
need an account, a DUA or a request form, call report_files with an empty list and \
say so in the note."""


def find_files_llm(client, settings: Settings, ds: dict, max_turns: int = 8) -> tuple[list[str], str]:
    from .crawler import PROBE_URL_TOOL, WEB_TOOLS, _create, _tool_result
    msgs: list[dict] = [{"role": "user", "content": "Dataset:\n" + json.dumps(
        {k: ds.get(k) for k in ("title", "url", "source", "description", "access_instructions",
                                "download_urls", "file_formats", "size")}, default=str)}]
    for _ in range(max_turns):
        resp = _create(client, settings, system=FIND_SYSTEM,
                       tools=[*WEB_TOOLS, PROBE_URL_TOOL, FIND_FILES_TOOL],
                       output_config={"effort": "low"}, messages=msgs)
        msgs.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason == "pause_turn":
            continue
        if resp.stop_reason != "tool_use":
            break
        results = []
        for b in resp.content:
            if b.type != "tool_use":
                continue
            if b.name == "report_files":
                urls = [u for u in (b.input or {}).get("urls", []) if str(u).startswith("http")]
                return urls[:5], str((b.input or {}).get("note", ""))
            if b.name == "probe_url":
                results.append(_tool_result(b.id, download.probe(
                    str((b.input or {}).get("url", "")), allow_private=settings.allow_private_hosts)))
            else:
                results.append(_tool_result(b.id, {"error": "unknown tool"}, True))
        msgs.append({"role": "user", "content": results})
    return [], "no files found"


# ------------------------------------------------------------------ manager
class ExploreManager:
    """Builds explore specs in a background thread; serves sources to the API."""

    def __init__(self, store: Store, settings: Settings, client_factory=None):
        self.store, self.settings = store, settings
        self.client_factory = client_factory
        self._jobs: dict[str, threading.Thread] = {}
        self._sources: dict[str, Any] = {}
        self._lock = threading.Lock()

    # -- storage
    def get(self, ds_id: str) -> dict | None:
        with self.store._conn() as c:
            row = c.execute("SELECT * FROM explore WHERE dataset_id = ?", (ds_id,)).fetchone()
            if not row:
                return None
            d = dict(row)
            for k in ("spec", "source", "job"):
                d[k] = json.loads(d[k]) if d[k] else None
            d["history"] = [dict(r) for r in c.execute(
                "SELECT version, prompt, reply, at FROM explore_history WHERE dataset_id = ?"
                " ORDER BY version DESC LIMIT 20", (ds_id,))]
            d["requests"] = [dict(r) for r in c.execute(
                "SELECT request, at FROM explore_requests WHERE dataset_id = ? ORDER BY id DESC"
                " LIMIT 20", (ds_id,))]
        return d

    def _save(self, ds_id: str, **fields) -> None:
        for k in ("spec", "source", "job"):
            if k in fields and fields[k] is not None and not isinstance(fields[k], str):
                fields[k] = json.dumps(fields[k])
        fields["updated_at"] = now_iso()
        with self.store._write() as c:
            if c.execute("SELECT 1 FROM explore WHERE dataset_id = ?", (ds_id,)).fetchone():
                c.execute(f"UPDATE explore SET {', '.join(f'{k} = ?' for k in fields)}"
                          " WHERE dataset_id = ?", [*fields.values(), ds_id])
            else:
                fields.setdefault("status", "pending")
                c.execute(f"INSERT INTO explore (dataset_id, {', '.join(fields)}) VALUES"
                          f" (?, {', '.join('?' * len(fields))})", [ds_id, *fields.values()])

    def _save_spec(self, ds_id: str, spec: dict, prompt: str | None) -> int:
        with self.store._write() as c:
            v = (c.execute("SELECT COALESCE(MAX(version), 0) FROM explore_history"
                           " WHERE dataset_id = ?", (ds_id,)).fetchone()[0]) + 1
            c.execute("INSERT INTO explore_history (dataset_id, version, spec, prompt, reply, at)"
                      " VALUES (?, ?, ?, ?, ?, ?)",
                      (ds_id, v, json.dumps(spec), prompt, spec.get("reply"), now_iso()))
            for req in spec.get("tool_requests") or []:
                c.execute("INSERT INTO explore_requests (dataset_id, request, at) VALUES (?, ?, ?)",
                          (ds_id, req[:500], now_iso()))
        self._save(ds_id, spec=spec, version=v, status="ready", error=None)
        return v

    # -- availability (cheap, no network): what the card's Explore button says
    def availability(self, ds: dict) -> dict:
        if HFSource.detect(ds):
            return {"available": True, "via": "huggingface"}
        if WFDBSource.detect(ds):
            return {"available": True, "via": "physionet"}
        if any(f.get("status") == "downloaded" for f in ds.get("files") or []):
            return {"available": True, "via": "files"}
        if ds.get("access_type") in ("open", "unknown"):
            return {"available": True, "via": "acquire"}
        return {"available": False, "via": None,
                "reason": "Needs access first (see How to access)."}

    # -- sources
    def explore_dir(self, ds_id: str) -> Path:
        return self.settings.data_dir / "explore" / ds_id

    def source(self, ds_id: str):
        if ds_id in self._sources:
            return self._sources[ds_id]
        ex = self.get(ds_id)
        info = (ex or {}).get("source") or {}
        via = info.get("via")
        if via == "huggingface":
            src = HFSource(info["repo"])
        elif via == "physionet":
            src = WFDBSource(info["pn_dir"])
        elif via == "files":
            src = FilesSource([Path(p) for p in info.get("paths", [])])
        else:
            raise SourceError("no data source yet")
        self._sources[ds_id] = src
        return src

    def _resolve(self, ds: dict, client, log_) -> dict:
        repo = HFSource.detect(ds)
        if repo:
            return {"via": "huggingface", "repo": repo}
        pn = WFDBSource.detect(ds)
        if pn:
            return {"via": "physionet", "pn_dir": pn}
        local = self.store.local_files(ds["id"])
        acq = self.explore_dir(ds["id"]) / "raw"
        if acq.exists() and any(acq.iterdir()):
            local.append(str(acq))
        if local:
            return {"via": "files", "paths": local}
        if ds.get("access_type") not in ("open", "unknown"):
            raise SourceError("This dataset needs credentials or an agreement before it can be "
                              "explored. " + (ds.get("access_instructions") or ""))
        urls = [u for u in ds.get("download_urls") or [] if u.startswith("http")]
        note = ""
        if not urls and client is not None:
            log_("searching for direct download links…")
            urls, note = find_files_llm(client, self.settings, ds)
        if not urls:
            raise SourceError("No direct download links found" + (f": {note}" if note else "."))
        got = []
        for u in urls[:5]:
            log_(f"downloading {u[:120]}")
            res = download.download(u, acq, self.settings.explore_max_mb * 1_000_000,
                                    allow_private=self.settings.allow_private_hosts)
            if res.status == "downloaded":
                got.append(res.local_path)
            else:
                log_(f"skipped: {res.note}")
        if not got:
            raise SourceError("Could not download any of the candidate files.")
        return {"via": "files", "paths": [str(acq)]}

    # -- jobs
    def busy(self, ds_id: str) -> bool:
        t = self._jobs.get(ds_id)
        return bool(t and t.is_alive())

    def build(self, ds_id: str) -> bool:
        with self._lock:
            if self.busy(ds_id):
                return False
            self._save(ds_id, status="building", error=None,
                       job={"started_at": now_iso(), "log": []})
            t = threading.Thread(target=self._build_safe, args=(ds_id,), daemon=True,
                                 name=f"explore-{ds_id}")
            self._jobs[ds_id] = t
            t.start()
            return True

    def _build_safe(self, ds_id: str) -> None:
        try:
            self.build_blocking(ds_id)
        except Exception as exc:
            log.exception("explore build %s failed", ds_id)
            self._save(ds_id, status="failed", error=f"{type(exc).__name__}: {str(exc)[:500]}"
                       if not isinstance(exc, SourceError) else str(exc)[:800])

    def build_blocking(self, ds_id: str) -> dict:
        ds = self.store.get_dataset(ds_id)
        if not ds:
            raise SourceError("dataset not found")
        job_log: list[str] = []

        def log_(msg: str) -> None:
            job_log.append(f"{now_iso()[11:19]} {msg}")
            self._save(ds_id, job={"log": job_log[-50:]})

        client = self.client_factory(self.settings) if self.client_factory else None
        log_("finding the data…")
        info = self._resolve(ds, client, log_)
        self._sources.pop(ds_id, None)
        self._save(ds_id, source=info)
        log_(f"reading a sample ({info['via']})…")
        src = self.source(ds_id)
        probe = src.probe()
        if probe.get("kind") == "none":
            raise SourceError("The files contain no images or tables we can read yet.")
        info["probe"] = probe
        self._save(ds_id, source=info)
        log_("composing the explore page…")
        spec = None
        if client is not None:
            try:
                spec = compose_llm(client, self.settings, ds, probe)
            except Exception as exc:
                log_(f"Claude compose failed ({type(exc).__name__}); using defaults")
        spec = validate_spec(spec or heuristic_spec(probe), probe)
        had = (self.get(ds_id) or {}).get("version")
        self._save_spec(ds_id, spec, "(rebuilt from the data)" if had else None)
        log_("ready")
        return spec

    def edit(self, ds_id: str, request: str) -> dict:
        ex = self.get(ds_id)
        if not ex or not ex.get("spec"):
            raise SourceError("build the explore page first")
        if self.client_factory is None:
            raise SourceError("editing needs ANTHROPIC_API_KEY")
        ds = self.store.get_dataset(ds_id)
        probe = (ex.get("source") or {}).get("probe") or {}
        spec = compose_llm(self.client_factory(self.settings), self.settings, ds, probe,
                           current={k: v for k, v in ex["spec"].items()
                                    if k not in ("reply", "tool_requests")},
                           request=request[:2000])
        spec = validate_spec(spec, probe)
        v = self._save_spec(ds_id, spec, request[:2000])
        return {"version": v, "reply": spec.get("reply"), "tool_requests": spec.get("tool_requests")}

    def revert(self, ds_id: str, version: int) -> None:
        with self.store._conn() as c:
            row = c.execute("SELECT spec FROM explore_history WHERE dataset_id = ? AND version = ?",
                            (ds_id, version)).fetchone()
        if not row:
            raise SourceError("no such version")
        spec = json.loads(row[0])
        spec["reply"] = f"Restored version {version}."
        spec["tool_requests"] = []
        self._save_spec(ds_id, spec, f"(restore version {version})")
