"""Bulk import from curated repositories' public catalog APIs.

The agent crawl finds the long tail; these importers list whole curated
sources in one pass, without spending a crawl on each dataset:

- **PhysioNet** (``/api/v1/project/published/``): every latest-version
  database and challenge, with its access policy (open / credentialed /
  restricted / contributor review), license, DOI and size.
- **TCIA** (``/api/v1/collections/``): every human imaging collection, with
  cancer types, modalities, subject counts, DOI and public/limited access.
- **OpenNeuro** (GraphQL): every dataset; most are cognitive-neuroscience
  studies of healthy volunteers, so only clinically relevant ones are kept.

Nothing is downloaded: each entry records what the data is and the exact
steps to obtain it. Claude (``DATASETS_MODEL``, low effort, batches of 25)
decides which records are clinically relevant and assigns canonical
conditions and modalities, reusing the catalog's existing condition names.
Without an API key a per-source heuristic does the categorization.

New entries flow into the existing pipeline: the literature worker links
their papers, and the FDA worker re-scans stored submission summaries for
them (see ``DeviceWorker.relink_step``).
"""
from __future__ import annotations

import html
import json
import logging
import re
import threading
from typing import Any, Callable, Iterable, Iterator

import requests

from .config import Settings
from .store import Store, now_iso

log = logging.getLogger(__name__)
_UA = {"User-Agent": "pahl-datasets importer (+https://datasets.paloaltohealthlabs.com)"}
BATCH = 25

PHYSIONET_API = "https://physionet.org/api/v1/project/published/"
TCIA_API = "https://www.cancerimagingarchive.net/api/v1/collections/"
OPENNEURO_API = "https://openneuro.org/crn/graphql"


def _text(s: str | None, limit: int = 900) -> str:
    """HTML fragment -> plain text, trimmed at a sentence near `limit`."""
    t = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) <= limit:
        return t
    cut = t[:limit]
    return (cut[:cut.rfind(". ") + 1] if ". " in cut[200:] else cut.rstrip() + "…")


def _gb(n: int | None) -> str:
    if not n:
        return ""
    for unit, size in (("TB", 1e12), ("GB", 1e9), ("MB", 1e6)):
        if n >= size:
            return f"{n / size:.1f} {unit}"
    return f"{n} bytes"


# ------------------------------------------------------------------ sources
# Each source yields candidate records: the dataset fields we can fill from
# the catalog, plus `hints` (source tags) for categorization.

PHYSIONET_ACCESS = {
    "Open": ("open", "Open access: no account needed. Download from the project page "
             "(\"Download the ZIP file\"), or mirror it with\n"
             "  wget -r -N -c -np https://physionet.org/files/{slug}/{version}/"),
    "Credentialed": ("credentialed",
                     "1. Create a PhysioNet account and apply for credentialed access "
                     "(identity check plus a reference).\n"
                     "2. Complete the required training (CITI \"Data or Specimens Only "
                     "Research\") and upload the certificate.\n"
                     "3. Sign the project's data use agreement on its page.\n"
                     "4. Download with your PhysioNet login:\n"
                     "  wget -r -N -c -np --user YOUR_USERNAME --ask-password "
                     "https://physionet.org/files/{slug}/{version}/"),
    "Restricted": ("dua", "1. Log in to PhysioNet.\n2. Sign the project's data use "
                   "agreement on its page.\n3. Download with your login:\n"
                   "  wget -r -N -c -np --user YOUR_USERNAME --ask-password "
                   "https://physionet.org/files/{slug}/{version}/"),
    "Contributor Review": ("request", "1. Log in to PhysioNet (credentialed account).\n"
                           "2. Submit an access request on the project page; the data "
                           "contributors review it.\n3. Once approved, download from the "
                           "project page with your login."),
}


def physionet(session: requests.Session) -> Iterator[dict]:
    resp = session.get(PHYSIONET_API, headers=_UA, timeout=120)
    resp.raise_for_status()
    for p in resp.json():
        if not p.get("is_latest_version") or p.get("resource_type") not in ("Database", "Challenge"):
            continue
        access, steps = PHYSIONET_ACCESS.get(p.get("access_policy"), PHYSIONET_ACCESS["Open"])
        doi = p.get("core_doi") or p.get("version_doi")
        yield {
            "title": p["title"], "url": p["source_url"], "source": "PhysioNet",
            "description": _text(f"{p.get('short_description') or ''} "
                                 f"{_text(p.get('abstract'), 700)}"),
            "license": (p.get("license") or {}).get("name") or "",
            "access_type": access,
            "access_instructions": steps.format(slug=p["slug"], version=p["version"]),
            "size": _gb(p.get("main_storage_size")),
            "citation": f"{p['title']} (version {p['version']}). PhysioNet"
                        f" ({p.get('publish_date', '')[:4]}). doi:{doi}" if doi else "",
            "tags": ["physionet", p["resource_type"].lower()],
            "hints": {"topics": p.get("topics") or []},
        }


def _tcia_pages(session: requests.Session) -> Iterator[dict]:
    page = 1
    while True:
        resp = session.get(TCIA_API, params={"per_page": 100, "page": page}, headers=_UA,
                           timeout=120)
        resp.raise_for_status()
        rows = resp.json()
        yield from rows
        if page >= int(resp.headers.get("X-WP-TotalPages", page)) or not rows:
            return
        page += 1


TCIA_STEPS = {
    "open": ("Open access (TCIA Data Usage Policy; cite the collection DOI).\n"
             "1. On the collection page, open the Data Access table and download the "
             ".tcia manifest for the files you want.\n"
             "2. Open the manifest with the NBIA Data Retriever "
             "(https://wiki.cancerimagingarchive.net/x/2QKPBQ) to download the images.\n"
             "Non-DICOM files (clinical data, pathology, annotations) download directly "
             "from the same table."),
    "dua": ("Limited access.\n1. Create a TCIA account.\n2. Sign the TCIA Restricted "
            "License Agreement for this collection (linked on the collection page) and "
            "email it to help@cancerimagingarchive.net.\n3. Once approved, log in and "
            "download the .tcia manifest; open it in the NBIA Data Retriever."),
}


def tcia(session: requests.Session) -> Iterator[dict]:
    for c in _tcia_pages(session):
        if "Human" not in (c.get("species") or []):
            continue
        title = html.unescape(c.get("collection_short_title") or c["title"]["rendered"])
        long = html.unescape(c.get("collection_title") or "")
        access = "dua" if c.get("collection_page_accessibility") == "Limited" else "open"
        types = [t for t in (c.get("cancer_types") or [])
                 if t not in ("Non-Cancer", "Not Applicable")]
        doi = c.get("collection_doi")
        yield {
            "title": f"{title}: {long}" if long and long.lower() != title.lower() else title,
            "url": c["link"], "source": "The Cancer Imaging Archive (TCIA)",
            "description": _text(c.get("collection_abstract") or c.get("collection_summary")),
            "license": "TCIA Data Usage Policy (see collection page for the specific license)",
            "access_type": access, "access_instructions": TCIA_STEPS[access],
            "n_subjects": str(c["subjects"]) if c.get("subjects") else "",
            "file_formats": ["dicom"] if c.get("data_types") else [],
            "citation": f"{title} [Data set]. The Cancer Imaging Archive. doi:{doi}" if doi else "",
            "tags": ["tcia"] + [t.lower() for t in (c.get("supporting_data") or [])],
            "hints": {"cancer_types": types, "locations": c.get("cancer_locations") or [],
                      "data_types": c.get("data_types") or [],
                      "status": c.get("collection_status")},
        }


OPENNEURO_QUERY = """query($after: String) { datasets(first: 100, after: $after) {
  pageInfo { hasNextPage endCursor }
  edges { node { id metadata { species studyDomain modalities dxStatus associatedPaperDOI }
    latestSnapshot { tag description { Name DatasetDOI License Authors }
      summary { modalities subjects size } } } } } }"""


def openneuro(session: requests.Session) -> Iterator[dict]:
    after = None
    while True:
        resp = session.post(OPENNEURO_API, json={"query": OPENNEURO_QUERY,
                                                 "variables": {"after": after}},
                            headers=_UA, timeout=120)
        resp.raise_for_status()
        data = resp.json()["data"]["datasets"]
        for edge in data["edges"] or []:
            n = (edge or {}).get("node")
            if not n:          # withdrawn / private datasets come back as null
                continue
            snap, meta = n.get("latestSnapshot") or {}, n.get("metadata") or {}
            desc, summ = snap.get("description") or {}, snap.get("summary") or {}
            if not desc.get("Name"):
                continue
            species = (meta.get("species") or "").lower()
            if species and "human" not in species:
                continue
            mods = sorted(set((summ.get("modalities") or []) + (meta.get("modalities") or [])))
            doi = desc.get("DatasetDOI") or ""
            subjects = summ.get("subjects") or []
            yield {
                "title": f"{desc['Name'].strip()} (OpenNeuro {n['id']})",
                "url": f"https://openneuro.org/datasets/{n['id']}",
                "source": "OpenNeuro",
                "description": "",
                "license": (desc.get("License") or "")[:120],
                "access_type": "open",
                "access_instructions":
                    "Open access, BIDS format. Download from the dataset page, or:\n"
                    f"  aws s3 sync --no-sign-request s3://openneuro.org/{n['id']} {n['id']}\n"
                    f"or with DataLad: datalad install https://github.com/OpenNeuroDatasets/{n['id']}.git",
                "n_subjects": str(len(subjects)) if subjects else "",
                "size": _gb(summ.get("size")),
                "file_formats": ["bids"],
                "citation": f"{desc['Name'].strip()}. OpenNeuro. doi:{doi.removeprefix('doi:')}"
                            if doi else "",
                "tags": ["openneuro"],
                "hints": {"modalities": mods, "study_domain": meta.get("studyDomain"),
                          "dx_status": meta.get("dxStatus"),
                          "paper_doi": meta.get("associatedPaperDOI")},
            }
        if not data["pageInfo"]["hasNextPage"]:
            return
        after = data["pageInfo"]["endCursor"]


SOURCES: dict[str, Callable[[requests.Session], Iterator[dict]]] = {
    "physionet": physionet, "tcia": tcia, "openneuro": openneuro}
SOURCE_LABEL = {"physionet": "PhysioNet", "tcia": "TCIA", "openneuro": "OpenNeuro"}


# ------------------------------------------------------------------ categorizing
CATEGORIZE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["records"],
    "properties": {"records": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["id", "relevant", "conditions", "modalities", "labels"],
        "properties": {
            "id": {"type": "integer"},
            "relevant": {"type": "boolean"},
            "conditions": {"type": "array", "items": {"type": "string"}},
            "modalities": {"type": "array", "items": {"type": "string"}},
            "labels": {"type": "string"},
        }}}},
}

CATEGORIZE_SYSTEM = """You categorize entries from a public data repository for a \
catalog of datasets used to build medical AI and software-as-a-medical-device.

For each record (by id):
- relevant: true if the data come from patients or people with a disease, injury or \
clinical state, or serve a clinical task (diagnosis, monitoring, prognosis, \
treatment), including datasets with healthy controls alongside patients and \
clinical-grade normative references (e.g. normal ECGs). false for basic cognitive or \
behavioral neuroscience in healthy volunteers, animal data, phantoms, software, and \
anything with no health application.
- conditions: canonical lowercase condition names (e.g. "atrial fibrillation", \
"glioblastoma", "obstructive sleep apnea"). Reuse a name from the existing list when \
one fits; otherwise use the standard clinical name, not an abbreviation. Use \
"healthy volunteers" only when there is no condition. Empty when not relevant.
- modalities: lowercase (e.g. "ecg", "eeg", "ppg", "mri", "ct", "pet", \
"chest x-ray", "pathology", "ehr", "imu", "polysomnography").
- labels: one short phrase on the ground truth / annotations if stated, else "".

Return every id."""


def categorize_llm(client, settings: Settings, recs: list[dict],
                   known: list[str]) -> dict[int, dict]:
    from .crawler import _create
    lines = [json.dumps({"id": i, "title": r["title"], "source": r["source"],
                         "description": r["description"][:600], **r.get("hints", {})})
             for i, r in enumerate(recs)]
    resp = _create(client, settings,
                   system=CATEGORIZE_SYSTEM + "\n\nExisting condition names: "
                   + "; ".join(known[:400]),
                   output_config={"effort": "low",
                                  "format": {"type": "json_schema", "schema": CATEGORIZE_SCHEMA}},
                   messages=[{"role": "user", "content": "\n".join(lines)}])
    if resp.stop_reason == "refusal":
        raise RuntimeError("categorization declined")
    out = json.loads(next(b.text for b in resp.content if b.type == "text"))
    return {r["id"]: r for r in out["records"] if 0 <= r["id"] < len(recs)}


_CLINICAL_WORDS = re.compile(
    r"(patient|disease|disorder|syndrome|cancer|tumou?r|carcinoma|stroke|epilep|seizure|"
    r"apnea|arrhythm|fibrillation|infarct|failure|injur|lesion|sclerosis|parkinson|"
    r"alzheimer|dementia|schizophren|depress|autis|diabet|sepsis|icu|intensive care|"
    r"clinical|hospital|surgery|surgical|pathology|fracture|covid|pneumonia|hypertension)", re.I)


_NO_DX = re.compile(r"healthy|control|^other$|^none$|^n/?a$|unknown", re.I)


def categorize_heuristic(r: dict) -> dict:
    h = r.get("hints", {})
    conds = [c.lower() for c in h.get("cancer_types", [])]
    dx = str(h.get("dx_status") or "").strip()
    dx = "" if _NO_DX.search(dx) else dx
    if dx:
        conds.append(dx.lower())
    text = f"{r['title']} {r['description']} {' '.join(h.get('topics', []))}"
    relevant = bool(conds) or bool(_CLINICAL_WORDS.search(text))
    if r["source"] == "OpenNeuro":   # mostly healthy-volunteer studies: need a signal
        relevant = bool(dx) or bool(_CLINICAL_WORDS.search(r["title"]))
    mods = [m.lower() for m in h.get("modalities", []) + h.get("data_types", [])]
    return {"relevant": relevant, "conditions": conds, "modalities": mods, "labels": ""}


# ------------------------------------------------------------------ runner
class ImportRunner:
    """Runs one source import at a time in a background thread; progress in kv."""

    def __init__(self, store: Store, settings: Settings, client_factory=None,
                 session: Any = None):
        self.store, self.settings = store, settings
        self.client_factory = client_factory
        self.session = session or requests.Session()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def status(self) -> dict:
        out = {}
        for src in SOURCES:
            raw = self.store.kv_get(f"import:{src}")
            out[src] = {"label": SOURCE_LABEL[src], **(json.loads(raw) if raw else {})}
        return out

    def busy(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self, source: str) -> bool:
        with self._lock:
            if self.busy() or source not in SOURCES:
                return False
            self._save(source, state="running", started_at=now_iso(), seen=0, relevant=0,
                       new=0, updated=0, error=None, finished_at=None)
            self._thread = threading.Thread(target=self._run_safe, args=(source,),
                                            name=f"import-{source}", daemon=True)
            self._thread.start()
            return True

    def _save(self, source: str, **fields) -> None:
        raw = self.store.kv_get(f"import:{source}")
        cur = json.loads(raw) if raw else {}
        cur.update(fields)
        self.store.kv_set(f"import:{source}", json.dumps(cur))

    def _run_safe(self, source: str) -> None:
        try:
            self.run(source)
        except Exception as exc:
            log.exception("import %s failed", source)
            self._save(source, state="failed", error=f"{type(exc).__name__}: {str(exc)[:300]}",
                       finished_at=now_iso())

    def run(self, source: str, limit: int | None = None) -> dict:
        """Import one source synchronously (also used by the CLI and tests)."""
        client = self.client_factory(self.settings) if self.client_factory else None
        counts = {"seen": 0, "relevant": 0, "new": 0, "updated": 0, "llm": bool(client)}
        batch: list[dict] = []

        def flush():
            if not batch:
                return
            cats: dict[int, dict] = {}
            if client is not None:
                try:
                    cats = categorize_llm(client, self.settings, batch,
                                          self.store.condition_names())
                except Exception as exc:  # one bad batch shouldn't stop the import
                    log.warning("categorization failed (%s); using heuristic", exc)
            for i, rec in enumerate(batch):
                cat = cats.get(i) or categorize_heuristic(rec)
                if not cat["relevant"]:
                    continue
                rec = {k: v for k, v in rec.items() if k != "hints"}
                rec["conditions"] = cat["conditions"]
                rec["modalities"] = list(dict.fromkeys(cat["modalities"]))
                rec["labels"] = rec.get("labels") or cat.get("labels") or ""
                rec["kind"] = "dataset"
                rec.setdefault("download_urls", [])
                _, is_new = self.store.upsert_dataset(rec, found_by=f"import:{source}")
                counts["relevant"] += 1
                counts["new" if is_new else "updated"] += 1
            batch.clear()
            self._save(source, **counts)

        for rec in SOURCES[source](self.session):
            counts["seen"] += 1
            batch.append(rec)
            if len(batch) >= BATCH:
                flush()
            if limit and counts["seen"] >= limit:
                break
        flush()
        self._save(source, state="done", finished_at=now_iso(), **counts)
        return counts


def run_sources(store: Store, settings: Settings, sources: Iterable[str],
                client_factory=None) -> dict:
    runner = ImportRunner(store, settings, client_factory)
    return {s: runner.run(s) for s in sources}
