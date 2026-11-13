"""Compatible datasets: which other datasets could go into the same model or
paper, for training, external validation or pretraining.

Two steps:

1. **Profile** each dataset (Claude, low effort, batches of 8; heuristic
   without a key): primary modality, body region, file formats, image size or
   sampling rate, views/protocol, population, and its label *targets* — each a
   condition or finding with its label type (classification, segmentation,
   detection, event, regression, report) and who produced the labels.
2. **Compare** profiles pairwise in code (no LLM), within the same modality.
   The score is *asymmetric*: from dataset A's side, a partner matters as much
   as the shared target matters to A. A pneumothorax-only set rates a
   23-finding chest X-ray set highly (it has the same label), while the
   23-finding set rates the pneumothorax-only set lower (it covers 1 of its
   23 tasks).

Score (0-100) = task (0-60: shared target, label-type match, how central the
target is to this dataset) + data (0-25: format, resolution / sampling rate,
views, body region) + population (0-15: age group, partner size).

Roles per pair:
- **train together**: same target and label type, data close enough to pool;
- **external validation**: same target, and no sign the two share patients
  (no common cohort name such as MIMIC or CheXpert in their titles);
- **pretraining**: same modality and region but no shared target.

Each pair carries the harmonization steps it needs (resize, resample, convert
formats, derive image-level labels from masks, collapse multi-label to binary)
and warnings (possible patient overlap, age mismatch).
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import threading
import time
from collections import defaultdict
from typing import Any, Iterable

from .config import Settings
from .store import Store, normalize_condition, now_iso

log = logging.getLogger(__name__)

MODALITIES = [
    "chest x-ray", "x-ray (other)", "mammography", "ct", "mri", "pet", "ultrasound",
    "echocardiography", "fundus", "oct", "dermatology photo", "pathology slide",
    "endoscopy", "dental x-ray", "ecg", "eeg", "emg", "ppg", "imu", "polysomnography",
    "physiological waveforms", "audio", "video", "ehr / tabular", "clinical text",
    "genomics", "other",
]
LABEL_TYPES = ["classification", "segmentation", "detection", "event", "regression", "report",
               "none"]
# Label types a target can be *derived* into (masks/boxes/events -> class labels).
_DERIVES = {("segmentation", "classification"), ("detection", "classification"),
            ("segmentation", "detection"), ("event", "classification")}
_IMAGE = {"chest x-ray", "x-ray (other)", "mammography", "ct", "mri", "pet", "ultrasound",
          "echocardiography", "fundus", "oct", "dermatology photo", "pathology slide",
          "endoscopy", "dental x-ray"}
_SIGNAL = {"ecg", "eeg", "emg", "ppg", "imu", "polysomnography", "physiological waveforms",
           "audio"}

PROFILE_ITEM = {
    "type": "object", "additionalProperties": False,
    "required": ["id", "modality", "other_modalities", "body_region", "formats", "image_size",
                 "sampling_hz", "channels", "views", "age_group", "countries", "n_subjects",
                 "targets"],
    "properties": {
        "id": {"type": "integer"},
        "modality": {"type": "string", "enum": MODALITIES},
        "other_modalities": {"type": "array", "items": {"type": "string", "enum": MODALITIES}},
        "body_region": {"type": "string"},
        "formats": {"type": "array", "items": {"type": "string"}},
        "image_size": {"type": "string"},
        "sampling_hz": {"type": ["number", "null"]},
        "channels": {"type": ["integer", "null"]},
        "views": {"type": "string"},
        "age_group": {"type": "string", "enum": ["adult", "pediatric", "neonatal", "mixed",
                                                  "unknown"]},
        "countries": {"type": "array", "items": {"type": "string"}},
        "n_subjects": {"type": ["integer", "null"]},
        "targets": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["name", "label_type", "annotator"],
            "properties": {
                "name": {"type": "string"},
                "label_type": {"type": "string", "enum": LABEL_TYPES},
                "annotator": {"type": "string", "enum": ["expert", "nlp-extracted", "clinical",
                                                         "automated", "self-report",
                                                         "unknown"]},
            }}},
    },
}
PROFILE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["profiles"],
                  "properties": {"profiles": {"type": "array", "items": PROFILE_ITEM}}}

PROFILE_SYSTEM = """You profile medical datasets so we can tell which ones can be \
combined in one model or study (pooled for training, used as an external test set, or \
for pretraining). For each dataset card (by id) fill:

- modality: the primary data type (enum); other_modalities: any others included.
- body_region: e.g. "chest", "brain", "heart", "retina", "wrist", "whole body"; "" if n/a.
- formats: file formats, lowercase (dicom, png, jpeg, nifti, edf, wfdb, csv, hdf5, \
bids, svs, mat).
- image_size: typical image dimensions as "WxH" or "WxHxD" (e.g. "1024x1024", \
"512x512x~120"); "" if not images or unknown.
- sampling_hz / channels: for signals (e.g. ECG 500 Hz, 12 channels); null otherwise.
- views: acquisition views or protocol (e.g. "PA/AP frontal", "T1, T2, FLAIR", \
"12-lead resting", "wrist-worn").
- age_group, countries (where data were collected), n_subjects (patients/subjects).
- targets: every label the data provides, one entry per condition or finding, named \
with standard lowercase clinical names (e.g. "pneumothorax", "atrial fibrillation", \
"diabetic retinopathy", "sleep stage"). label_type: classification (per image/record), \
segmentation (masks), detection (boxes/points), event (time-stamped annotations), \
regression (continuous value, e.g. ejection fraction), report (free-text reports \
only), none (no labels). annotator: who produced the labels.

Use what the card states plus well-documented, published facts about the named \
dataset (e.g. ChestX-ray14 has 14 NLP-extracted labels on 1024x1024 PNGs). Use "" / \
null / "unknown" rather than guessing. Return every id."""


def card_hash(ds: dict) -> str:
    keys = ("title", "description", "labels", "size", "n_subjects", "file_formats",
            "modalities", "conditions")
    return hashlib.sha1(json.dumps([ds.get(k) for k in keys], sort_keys=True,
                                   default=str).encode()).hexdigest()[:16]


def _card(ds: dict) -> dict:
    return {"title": ds["title"], "source": ds.get("source"),
            "description": (ds.get("description") or "")[:700],
            "labels": ds.get("labels"), "size": ds.get("size"),
            "n_subjects": ds.get("n_subjects"), "formats": ds.get("file_formats"),
            "modalities": ds.get("modalities"), "conditions": ds.get("conditions")}


def profile_llm(client, settings: Settings, batch: list[dict]) -> dict[str, dict]:
    from .crawler import _create
    lines = [json.dumps({"id": i, **_card(d)}) for i, d in enumerate(batch)]
    resp = _create(client, settings, system=PROFILE_SYSTEM,
                   output_config={"effort": "low",
                                  "format": {"type": "json_schema", "schema": PROFILE_SCHEMA}},
                   messages=[{"role": "user", "content": "\n".join(lines)}])
    if resp.stop_reason == "refusal":
        raise RuntimeError("profiling declined")
    out = json.loads(next(b.text for b in resp.content if b.type == "text"))
    res = {}
    for p in out["profiles"]:
        if 0 <= p["id"] < len(batch):
            res[batch[p.pop("id")]["id"]] = clean_profile(p)
    return res


_MOD_WORDS = [  # (regex on the card's modality strings, enum value)
    (r"chest x-?ray|cxr|chest radiograph", "chest x-ray"), (r"mammog", "mammography"),
    (r"dental|panoramic|periapical", "dental x-ray"), (r"x-?ray|radiograph|\bdx\b|\bcr\b", "x-ray (other)"),
    (r"\bct\b|computed tomography", "ct"), (r"\bmri?\b|magnetic resonance|\bmr\b", "mri"),
    (r"\bpet\b", "pet"), (r"echocardio", "echocardiography"), (r"ultrasound|sonograph|\bus\b", "ultrasound"),
    (r"fundus", "fundus"), (r"\boct\b", "oct"), (r"dermo|skin", "dermatology photo"),
    (r"patholog|histolog|whole.slide|\bwsi\b", "pathology slide"), (r"endoscop|colonoscop", "endoscopy"),
    (r"\becg\b|\bekg\b|electrocardio", "ecg"), (r"\beeg\b|ieeg|electroenceph", "eeg"),
    (r"\bemg\b", "emg"), (r"\bppg\b|photoplethysm", "ppg"),
    (r"\bimu\b|acceleromet|gyroscop|inertial|actigraph", "imu"),
    (r"polysomno|\bpsg\b", "polysomnography"), (r"waveform|vital|abp|arterial", "physiological waveforms"),
    (r"audio|sound|phonocardio|stethoscop", "audio"), (r"video", "video"),
    (r"\behr\b|tabular|clinical data|claims|registry", "ehr / tabular"),
    (r"note|report|text", "clinical text"), (r"genom|sequenc|rna|dna|express", "genomics"),
]


def heuristic_profile(ds: dict) -> dict:
    mods = []
    for m in ds.get("modalities") or []:
        for pat, val in _MOD_WORDS:
            if re.search(pat, m, re.I) and val not in mods:
                mods.append(val)
                break
    return clean_profile({
        "modality": mods[0] if mods else "other", "other_modalities": mods[1:],
        "body_region": "", "formats": ds.get("file_formats") or [], "image_size": "",
        "sampling_hz": None, "channels": None, "views": "", "age_group": "unknown",
        "countries": [], "n_subjects": _int(ds.get("n_subjects")),
        "targets": [{"name": c, "label_type": "classification", "annotator": "unknown"}
                    for c in ds.get("conditions") or [] if c != "healthy volunteers"]})


def _int(v: Any) -> int | None:
    m = re.search(r"\d[\d,]*", str(v or ""))
    try:
        return int(m.group().replace(",", "")) if m else None
    except ValueError:
        return None


def clean_profile(p: dict) -> dict:
    p = dict(p)
    p["formats"] = sorted({f.lower().strip(".") for f in p.get("formats") or [] if f})
    seen, targets = set(), []
    for t in p.get("targets") or []:
        name = normalize_condition(t["name"])
        if name and (name, t["label_type"]) not in seen and t["label_type"] != "none":
            seen.add((name, t["label_type"]))
            targets.append({**t, "name": name})
    p["targets"] = targets
    return p


# ------------------------------------------------------------------ comparing
def _dims(s: str) -> list[float]:
    return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", s or "")][:3]


def _tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(w) > 1}


_GENERIC = {"DATA", "DATASET", "DATABASE", "OPEN", "CHALLENGE", "STUDY", "TCIA", "PHYSIONET",
            "COVID", "OPENNEURO", "KAGGLE", "MICCAI", "IEEE", "NIH", "THE", "AND", "WITH",
            "VERSION", "CLINICAL", "IMAGES", "MULTI", "LARGE", "PUBLIC", "CXR", "ECG", "EKG",
            "EEG", "MRI", "PET", "ICU", "JPG", "PNG", "DICOM", "BIDS", "UCI", "RSNA", "ISBI"}


def _cohort_tokens(title: str) -> set[str]:
    """Distinctive cohort names in a title (MIMIC, CHEXPERT, UKBB...), per
    hyphen segment so MIMIC-CXR-JPG and MIMIC-CXR-LT both yield MIMIC."""
    return {w.upper() for w in re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", title or "")
            if sum(c.isupper() for c in w) >= 3} - _GENERIC


def compare(a: dict, b: dict, pa: dict, pb: dict) -> dict | None:
    """How useful dataset b is to someone working with dataset a. None if
    unrelated. a/b are dataset rows (id, title, source, url), pa/pb profiles."""
    mods_a = {pa["modality"], *pa.get("other_modalities", [])} - {"other"}
    mods_b = {pb["modality"], *pb.get("other_modalities", [])} - {"other"}
    shared_mods = mods_a & mods_b
    if not shared_mods:
        return None
    mod = pa["modality"] if pa["modality"] in shared_mods else sorted(shared_mods)[0]

    # Task: best shared target from a's point of view.
    ta = defaultdict(list)
    for t in pa["targets"]:
        ta[t["name"]].append(t)
    tb = defaultdict(list)
    for t in pb["targets"]:
        tb[t["name"]].append(t)
    n_a = max(1, len(ta))
    shared, best = [], 0.0
    for name in ta.keys() & tb.keys():
        match, how = 0.0, ""
        for x in ta[name]:
            for y in tb[name]:
                if x["label_type"] == y["label_type"]:
                    m, h = 1.0, x["label_type"]
                elif (y["label_type"], x["label_type"]) in _DERIVES:
                    m, h = 0.75, f"{y['label_type']} → {x['label_type']}"
                elif (x["label_type"], y["label_type"]) in _DERIVES:
                    m, h = 0.6, f"{y['label_type']} (yours: {x['label_type']})"
                elif "report" in (x["label_type"], y["label_type"]):
                    m, h = 0.4, "labels from reports"
                else:
                    m, h = 0.5, f"{y['label_type']} vs {x['label_type']}"
                if y.get("annotator") == "expert":
                    m = min(1.0, m + 0.05)
                if m > match:
                    match, how = m, h
        shared.append({"target": name, "label_match": round(match, 2), "how": how})
        best = max(best, match)
    shared.sort(key=lambda s: -s["label_match"])
    centrality = len(shared) / n_a if shared else 0.0          # share of a's tasks covered
    task = (60 * best * (0.5 + 0.5 * min(1.0, centrality))) if shared else 0.0

    # Data compatibility.
    data, notes = 0.0, []
    fa, fb = set(pa["formats"]), set(pb["formats"])
    if fa & fb:
        data += 6
    elif fa and fb:
        data += 2
        notes.append(f"Convert {'/'.join(sorted(fb))} → {'/'.join(sorted(fa))}")
    else:
        data += 3
    if mod in _IMAGE:
        da, db = _dims(pa.get("image_size", "")), _dims(pb.get("image_size", ""))
        if da and db:
            r = max(da[0], db[0]) / max(1.0, min(da[0], db[0]))
            data += 8 if r <= 1.5 else 4 if r <= 3 else 1
            if r > 1.5:
                notes.append(f"Resize {pb['image_size']} → {pa['image_size']}")
        else:
            data += 4
    elif mod in _SIGNAL:
        sa, sb = pa.get("sampling_hz"), pb.get("sampling_hz")
        if sa and sb:
            r = max(sa, sb) / max(1e-9, min(sa, sb))
            data += 8 if r < 1.01 else 5 if r <= 2.5 else 2
            if r >= 1.01:
                notes.append(f"Resample {sb:g} Hz → {sa:g} Hz")
        else:
            data += 4
        ca, cb = pa.get("channels"), pb.get("channels")
        if ca and cb and ca != cb:
            notes.append(f"{cb} vs {ca} channels/leads: select a common subset")
    else:
        data += 4
    if _tokens(pa.get("views", "")) & _tokens(pb.get("views", "")):
        data += 5
    elif pa.get("views") and pb.get("views"):
        notes.append(f"Different views/protocol: {pb['views']} vs {pa['views']}")
    else:
        data += 2
    ra, rb = (pa.get("body_region") or "").lower(), (pb.get("body_region") or "").lower()
    if ra and rb:
        data += 6 if (_tokens(ra) & _tokens(rb)) else 0
    else:
        data += 3

    # Population.
    pop = 0.0
    aa, ab = pa.get("age_group", "unknown"), pb.get("age_group", "unknown")
    if aa == ab and aa != "unknown" or "mixed" in (aa, ab):
        pop += 10
    elif "unknown" in (aa, ab):
        pop += 5
    else:
        notes.append(f"Age mismatch: {ab} vs {aa}")
    nb = pb.get("n_subjects")
    pop += 5 * min(1.0, math.log10(nb) / 4) if nb and nb > 1 else 2

    if not shared:
        # Same data type, no shared label: pretraining / domain adaptation only.
        if not (ra and rb and _tokens(ra) & _tokens(rb)) and mod not in _SIGNAL:
            return None
        score = min(35.0, 0.5 * (data + pop))
        return {"score": round(score, 1), "roles": ["pretraining"], "shared": [],
                "modality": mod, "notes": notes[:4], "warnings": []}

    warnings = []
    overlap = _cohort_tokens(a["title"]) & _cohort_tokens(b["title"])
    if overlap:
        warnings.append(f"May share patients ({', '.join(sorted(overlap))}): don't use one to "
                        "validate the other")
    roles = []
    top = shared[0]
    if top["label_match"] >= 0.95 and data >= 14 and not any(w.startswith("Age") for w in notes):
        roles.append("train together")
    # Repositories host many unrelated cohorts (two PhysioNet databases are
    # different patients), so only a shared cohort name blocks validation.
    if top["label_match"] >= 0.6 and not overlap:
        roles.append("external validation")
        if "yours:" in top["how"]:
            notes.insert(0, f"Validates at the {top['how'].split()[0]} level only "
                            f"(its labels are coarser than yours)")
    if not roles:
        roles.append("related task")
    if len(tb) > 1 and top["target"] in tb:
        notes.insert(0, f"Use its {top['target']} labels; {len(tb) - 1} other "
                        f"{'target' if len(tb) == 2 else 'targets'} can be dropped or kept as auxiliary tasks")
    if "→" in top["how"]:
        notes.insert(0, f"Derive {top['how'].split('→ ')[-1]} labels from its {top['how'].split(' →')[0]}")
    return {"score": round(min(100.0, task + data + pop), 1), "roles": roles,
            "shared": shared[:6], "modality": mod, "notes": notes[:5], "warnings": warnings}


def compute_relations(datasets: list[dict], profiles: dict[str, dict],
                      per_dataset: int = 30) -> list[tuple]:
    """All directed relations, best `per_dataset` per dataset."""
    by_mod: dict[str, list[str]] = defaultdict(list)
    for ds_id, p in profiles.items():
        for m in {p["modality"], *p.get("other_modalities", [])} - {"other"}:
            by_mod[m].append(ds_id)
    rows = {d["id"]: d for d in datasets}
    out: dict[str, list[tuple]] = defaultdict(list)
    for ids in by_mod.values():
        for a in ids:
            for b in ids:
                if a == b or a not in rows or b not in rows:
                    continue
                if any(r[1] == b for r in out[a]):
                    continue
                rel = compare(rows[a], rows[b], profiles[a], profiles[b])
                if rel:
                    out[a].append((a, b, rel))
    flat = []
    for a, rels in out.items():
        rels.sort(key=lambda r: -r[2]["score"])
        flat += rels[:per_dataset]
    return flat


# ------------------------------------------------------------------ worker
class CompatWorker:
    """Profiles datasets whose card changed, then recomputes relations."""

    BATCH = 8

    def __init__(self, store: Store, settings: Settings, client_factory=None):
        self.store, self.settings = store, settings
        self.client_factory = client_factory
        self._client = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_error: str | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="compat", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                worked = self.step()
            except Exception as exc:
                log.exception("compat step failed")
                self.last_error = f"{type(exc).__name__}: {str(exc)[:300]}"
                worked = False
            self._stop.wait(self.settings.lit_interval_sec if worked else 60)

    def run_until_idle(self, max_steps: int = 10_000) -> int:
        n = 0
        while n < max_steps and self.step():
            n += 1
        return n

    def step(self) -> bool:
        todo = self.store.datasets_needing_profile(card_hash, self.BATCH)
        if todo:
            self.profile(todo)
            self.store.kv_set("compat_dirty", now_iso())
            return True
        if self.store.kv_get("compat_dirty"):
            self.recompute()
            return True
        return False

    def profile(self, batch: list[dict]) -> None:
        if self._client is None and self.client_factory is not None:
            self._client = self.client_factory(self.settings)
        got: dict[str, dict] = {}
        source = "heuristic"
        if self._client is not None:
            try:
                got, source = profile_llm(self._client, self.settings, batch), "llm"
            except Exception as exc:
                log.warning("profiling failed (%s); heuristic for this batch", exc)
                self.last_error = f"profiling: {type(exc).__name__}: {str(exc)[:200]}"
        for d in batch:
            p = got.get(d["id"]) or heuristic_profile(d)
            self.store.save_profile(d["id"], p, card_hash(d),
                                    source if d["id"] in got else "heuristic")

    def recompute(self) -> None:
        t = time.monotonic()
        datasets, profiles = self.store.all_profiles()
        rows = compute_relations(datasets, profiles)
        self.store.replace_relations(rows)
        self.store.kv_set("compat_dirty", "")
        self.store.kv_set("compat_computed", json.dumps(
            {"at": now_iso(), "relations": len(rows), "datasets": len(profiles),
             "seconds": round(time.monotonic() - t, 1)}))
