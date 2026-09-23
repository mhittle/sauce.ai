"""Literature linker: associate journal articles with each catalog dataset.

A background worker that, for every dataset:

1. **Resolves** its descriptor paper(s) — the publication(s) that introduced
   the dataset — and a few precise name aliases ("BraTS 2021", "MIMIC-IV").
   Candidates come from DOIs on the card plus title searches in Europe PMC
   (and OpenAlex when a key is set); an LLM call picks the right ones and
   proposes aliases (falls back to a heuristic without an API key).
2. **Harvests** articles in priority order, one page per step:
   - ``cites``: papers that cite a descriptor paper (Europe PMC "cited by";
     OpenAlex ``cites:`` sorted by citation count);
   - ``mentions``: papers whose text names the dataset (Europe PMC full-text
     search sorted by citations; OpenAlex full-text search).
   Every page is kept, so over time the goal is *every* article; highest-
   cited ones land first because each stream is sorted by citations and
   datasets are worked round-robin.
3. **Refreshes** completed datasets every ``DATASETS_LIT_REFRESH_DAYS`` to
   pick up new papers and updated citation counts.

Sources: Europe PMC REST (no key) and OpenAlex (``OPENALEX_API_KEY``,
optional — OpenAlex now requires a free key for meaningful volume).
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Any, Iterable

import requests

from .config import Settings
from .store import Store

log = logging.getLogger(__name__)

EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
OPENALEX = "https://api.openalex.org"
_UA = {"User-Agent": "sauce.ai-datasets literature linker (+https://sauce.ai)"}
_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>)\],;]+)", re.I)
_OA_SELECT = ("id,doi,display_name,publication_year,cited_by_count,ids,"
              "primary_location,authorships")
EPMC_PAGE = 1000
OA_PAGE = 200


class TransientError(RuntimeError):
    """Source unavailable / rate-limited; retry this page later."""


# ------------------------------------------------------------------ HTTP
class Http:
    def __init__(self, settings: Settings, session: Any = None, sleep=time.sleep):
        self.settings = settings
        self.session = session or requests.Session()
        self.sleep = sleep

    def get_json(self, url: str, params: dict | None = None, tries: int = 3) -> dict | None:
        """GET → JSON. None on 404; TransientError after retries on 429/5xx/network."""
        params = dict(params or {})
        if url.startswith(OPENALEX):
            if self.settings.openalex_api_key:
                params["api_key"] = self.settings.openalex_api_key
            if self.settings.openalex_mailto:
                params["mailto"] = self.settings.openalex_mailto
        delay = 2.0
        for attempt in range(tries):
            try:
                resp = self.session.get(url, params=params, headers=_UA, timeout=30)
            except requests.RequestException as exc:
                err = f"network: {exc}"
            else:
                if resp.status_code == 404:
                    return None
                if resp.status_code == 200:
                    try:
                        body = resp.json()
                    except ValueError:
                        err = "invalid JSON"
                    else:
                        # Europe PMC reports outages as 200 + errCode.
                        if isinstance(body, dict) and body.get("errCode"):
                            err = f"{body.get('errCode')}: {body.get('errMsg')}"
                        else:
                            return body
                elif resp.status_code in (429, 500, 502, 503, 504):
                    err = f"HTTP {resp.status_code}"
                else:
                    raise TransientError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            if attempt < tries - 1:
                self.sleep(delay)
                delay *= 2.5
        raise TransientError(err)


# ------------------------------------------------------------------ records
def norm_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    d = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", doi.strip(), flags=re.I)
    return d.rstrip(".").lower() or None


def find_dois(*texts: str | None) -> list[str]:
    out = []
    for t in texts:
        for m in _DOI_RE.finditer(t or ""):
            out.append(norm_doi(m.group(1)))
        z = re.search(r"zenodo\.org/(?:record|records)/(\d+)", t or "")
        if z:
            out.append(f"10.5281/zenodo.{z.group(1)}")
    return [d for d in dict.fromkeys(out) if d]


def article_key(pmid=None, doi=None, openalex_id=None, fallback=None) -> str:
    if pmid:
        return f"pmid:{pmid}"
    if doi:
        return f"doi:{doi}"
    if openalex_id:
        return f"openalex:{openalex_id}"
    return fallback


def from_epmc(r: dict) -> dict:
    """Europe PMC search hit or citation entry → article dict."""
    src, rid = r.get("source"), str(r.get("id") or "")
    pmid = r.get("pmid") or (rid if src == "MED" else None)
    doi = norm_doi(r.get("doi"))
    url = (f"https://doi.org/{doi}" if doi else
           f"https://europepmc.org/article/{src}/{rid}" if src and rid else None)
    year = r.get("pubYear")
    return {
        "id": article_key(pmid, doi, None, f"epmc:{src}:{rid}"),
        "pmid": pmid, "doi": doi, "pmcid": r.get("pmcid"),
        "title": (r.get("title") or "").strip() or "(untitled)",
        "authors": r.get("authorString"),
        "venue": r.get("journalTitle") or r.get("journalAbbreviation"),
        "year": int(year) if str(year or "").isdigit() else None,
        "cited_by_count": int(r.get("citedByCount") or 0),
        "url": url,
        "_epmc": f"{src}:{rid}" if src and rid else None,
    }


def from_openalex(w: dict) -> dict:
    oa_id = (w.get("id") or "").rsplit("/", 1)[-1] or None
    ids = w.get("ids") or {}
    pmid = (ids.get("pmid") or "").rsplit("/", 1)[-1] or None
    doi = norm_doi(w.get("doi"))
    authors = ", ".join(a.get("author", {}).get("display_name", "")
                        for a in (w.get("authorships") or [])[:6])
    venue = (((w.get("primary_location") or {}).get("source") or {}).get("display_name"))
    return {
        "id": article_key(pmid, doi, oa_id),
        "pmid": pmid, "doi": doi, "openalex_id": oa_id,
        "pmcid": (ids.get("pmcid") or "").rsplit("/", 1)[-1] or None,
        "title": (w.get("display_name") or "").strip() or "(untitled)",
        "authors": authors or None, "venue": venue,
        "year": w.get("publication_year"),
        "cited_by_count": int(w.get("cited_by_count") or 0),
        "url": f"https://doi.org/{doi}" if doi else w.get("id"),
    }


def save_article(store: Store, art: dict) -> str:
    """Upsert, reusing an existing row matched by pmid/doi/openalex id."""
    existing = store.find_article_id(art.get("pmid"), art.get("doi"), art.get("openalex_id"))
    art = {k: v for k, v in art.items() if not k.startswith("_")}
    if existing:
        art["id"] = existing
    return store.upsert_article(art)


# ------------------------------------------------------------------ resolution
def _epmc_search(http: Http, query: str, page_size: int = 8, sort: str | None = None,
                 cursor: str = "*") -> dict:
    params = {"query": query, "format": "json", "resultType": "lite",
              "pageSize": page_size, "cursorMark": cursor}
    if sort:
        params["sort"] = sort
    return http.get_json(f"{EPMC}/search", params) or {}


def gather_candidates(ds: dict, http: Http) -> list[dict]:
    """Possible descriptor papers: DOI matches first, then title searches."""
    cands: dict[str, dict] = {}

    def add(art: dict, why: str):
        art.setdefault("_why", why)
        cands.setdefault(art["id"], art)

    oa = bool(http.settings.openalex_api_key)
    for doi in find_dois(ds.get("citation"), ds.get("url"), ds.get("description"),
                         *ds.get("download_urls", [])):
        body = _epmc_search(http, f'DOI:"{doi}"', page_size=1)
        for r in (body.get("resultList") or {}).get("result", []):
            add(from_epmc(r), "doi")
        if oa:
            w = http.get_json(f"{OPENALEX}/works/doi:{doi}", {"select": _OA_SELECT})
            if w:
                add(from_openalex(w), "doi")
    queries = [ds["title"]]
    if ds.get("citation"):
        queries.append(re.sub(r"\s+", " ", ds["citation"])[:200])
    for q in queries:
        terms = " ".join(re.findall(r"[A-Za-z0-9]{3,}", q))[:250]
        if not terms:
            continue
        body = _epmc_search(http, terms, page_size=8)
        for r in (body.get("resultList") or {}).get("result", []):
            add(from_epmc(r), "search")
        if oa:
            res = http.get_json(f"{OPENALEX}/works", {"search": terms, "per_page": 8,
                                                     "select": _OA_SELECT}) or {}
            for w in res.get("results", []):
                add(from_openalex(w), "search")
    return list(cands.values())


RESOLVE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["descriptor_ids", "extra_descriptor_dois", "aliases", "note"],
    "properties": {
        "descriptor_ids": {"type": "array", "items": {"type": "string"}},
        "extra_descriptor_dois": {"type": "array", "items": {"type": "string"}},
        "aliases": {"type": "array", "items": {"type": "string"}},
        "note": {"type": "string"},
    },
}

RESOLVE_SYSTEM = """You link medical datasets to the scientific literature.

Given a dataset card and candidate papers, return:
- descriptor_ids: ids (from the candidate list only) of the paper(s) that \
introduced or formally describe this dataset — the paper authors are asked to cite \
when they use it. Usually one; include a challenge overview paper if the dataset \
is a challenge release. Empty if none of the candidates is one.
- extra_descriptor_dois: DOIs of descriptor papers you are confident about that are \
missing from the candidates. Empty if unsure; never guess.
- aliases: 1-5 exact phrases papers use to name this dataset in their text \
("BraTS 2021", "MIMIC-IV", "SIIM-ACR Pneumothorax"). They are used as exact-phrase \
full-text searches, so each must be specific to this dataset: no generic phrases \
("brain MRI dataset"), no bare common words or acronyms under 4 characters.
- note: one sentence on your confidence."""


def llm_resolve(client, settings: Settings, ds: dict, cands: list[dict]) -> dict:
    from .crawler import _create  # shared request defaults (thinking, caching, fallbacks)
    lines = [f"{c['id']} | {c['title']} | {c.get('year') or ''} | {c.get('venue') or ''} |"
             f" cited {c.get('cited_by_count', 0)} | doi {c.get('doi') or '-'} | via {c['_why']}"
             for c in cands] or ["(no candidates found)"]
    card = {k: ds.get(k) for k in ("title", "url", "source", "description", "citation",
                                   "conditions", "modalities", "tags")}
    resp = _create(
        client, settings, system=RESOLVE_SYSTEM,
        output_config={"effort": "low",
                       "format": {"type": "json_schema", "schema": RESOLVE_SCHEMA}},
        messages=[{"role": "user", "content": "Dataset card:\n" + json.dumps(card, indent=1)
                   + "\n\nCandidate papers (id | title | year | venue | citations | doi):\n"
                   + "\n".join(lines)}])
    if resp.stop_reason == "refusal":
        raise RuntimeError("resolution request declined")
    out = json.loads(next(b.text for b in resp.content if b.type == "text"))
    valid = {c["id"] for c in cands}
    out["descriptor_ids"] = [i for i in out["descriptor_ids"] if i in valid]
    return out


_COMMON = {"data", "dataset", "database", "challenge", "open", "public", "image", "images",
           "study", "clinical", "medical", "version", "release"}
# Acronyms that appear in dataset titles but name venues/modalities/agencies,
# not the dataset; as full-text searches they'd pull in unrelated papers.
_GENERIC_ACRONYMS = {"miccai", "isbi", "rsna", "spie", "ieee", "nih", "nlm", "tcia", "ukbb",
                     "covid", "covid-19", "sars-cov-2", "mri", "fmri", "ct", "pet", "eeg",
                     "ecg", "ekg", "emr", "ehr", "icu", "usa", "kaggle", "zenodo"}
_DATASETY = ("dataset", "database", "challenge", "benchmark", "cohort", "archive",
             "collection", "corpus", "repository", "resource")


def heuristic_resolve(ds: dict, cands: list[dict]) -> dict:
    """No-LLM fallback: DOI hits and near-title matches as descriptors; the
    title (if distinctive) and acronym-like tokens as aliases."""
    title_terms = set(re.findall(r"[a-z0-9]{3,}", ds["title"].lower())) - _COMMON
    desc = []
    for c in cands:
        terms = set(re.findall(r"[a-z0-9]{3,}", c["title"].lower())) - _COMMON
        overlap = len(title_terms & terms) / max(1, len(title_terms))
        # A title match only counts for a paper that presents a dataset;
        # otherwise every paper titled "... on CheXpert" would qualify.
        presents = any(w in c["title"].lower() for w in _DATASETY)
        if c["_why"] == "doi" or (title_terms and overlap >= 0.8 and presents):
            desc.append(c["id"])
    aliases = []
    words = ds["title"].split()
    if 2 <= len(words) <= 8 and len(ds["title"]) >= 8 and re.fullmatch(r"[\w\s-]+", ds["title"]):
        aliases.append(ds["title"])
    for tok in re.findall(r"\b[A-Za-z][A-Za-z0-9-]{3,}\b", ds["title"]):
        if sum(ch.isupper() for ch in tok) >= 2 or any(ch.isdigit() for ch in tok):
            if tok.lower() not in _COMMON | _GENERIC_ACRONYMS:
                aliases.append(tok)
    return {"descriptor_ids": desc, "extra_descriptor_dois": [],
            "aliases": list(dict.fromkeys(aliases))[:5], "note": "heuristic (no LLM)"}


def clean_aliases(aliases: Iterable[str]) -> list[str]:
    out = []
    for a in aliases:
        a = re.sub(r"\s+", " ", str(a).replace('"', "")).strip()
        if len(a) >= 4 and a.lower() not in _COMMON | _GENERIC_ACRONYMS:
            out.append(a)
    return list(dict.fromkeys(out))[:5]


def build_streams(descriptors: list[dict], aliases: list[str], openalex: bool) -> list[dict]:
    """Cites streams first (higher-precision, and what the user ranks first),
    then name-mention streams."""
    streams = []
    for d in descriptors:
        if d.get("epmc"):
            streams.append({"kind": "epmc_cites", "ref": d["epmc"]})
        if openalex and d.get("openalex_id"):
            streams.append({"kind": "openalex_cites", "ref": d["openalex_id"]})
    for a in aliases:
        streams.append({"kind": "epmc_mentions", "ref": a})
        if openalex:
            streams.append({"kind": "openalex_mentions", "ref": a})
    for s in streams:
        s.update(cursor=None, done=False, fetched=0, error=None)
    return streams


# ------------------------------------------------------------------ harvesting
def fetch_page(http: Http, stream: dict, max_mention_hits: int) -> tuple[list[dict], Any, bool, str | None]:
    """One page of a stream. Returns (articles, next_cursor, done, note)."""
    kind, ref, cur = stream["kind"], stream["ref"], stream.get("cursor")
    if kind == "epmc_cites":
        src, rid = ref.split(":", 1)
        page = int(cur or 1)
        body = http.get_json(f"{EPMC}/{src}/{rid}/citations",
                             {"page": page, "pageSize": EPMC_PAGE, "format": "json"}) or {}
        items = [from_epmc(r) for r in (body.get("citationList") or {}).get("citation", [])]
        done = page * EPMC_PAGE >= int(body.get("hitCount") or 0) or not items
        return items, page + 1, done, None
    if kind == "epmc_mentions":
        cursor = cur or "*"
        body = _epmc_search(http, f'"{ref}"', page_size=EPMC_PAGE, sort="CITED desc",
                            cursor=cursor)
        items = [from_epmc(r) for r in (body.get("resultList") or {}).get("result", [])]
        nxt = body.get("nextCursorMark")
        done = not items or not nxt or nxt == cursor or len(items) < EPMC_PAGE
        hits = int(body.get("hitCount") or 0)
        if cursor == "*" and max_mention_hits and hits > max_mention_hits:
            # Too broad to be dataset-specific: keep the top-cited page only.
            return items, nxt, True, f"alias matched {hits} papers; kept top {len(items)}"
        return items, nxt, done, None
    if kind in ("openalex_cites", "openalex_mentions"):
        cursor = cur or "*"
        params = {"per_page": OA_PAGE, "cursor": cursor, "sort": "cited_by_count:desc",
                  "select": _OA_SELECT}
        if kind == "openalex_cites":
            params["filter"] = f"cites:{ref}"
        else:
            params["search"] = f'"{ref}"'
        body = http.get_json(f"{OPENALEX}/works", params) or {}
        items = [from_openalex(w) for w in body.get("results", [])]
        nxt = (body.get("meta") or {}).get("next_cursor")
        hits = int((body.get("meta") or {}).get("count") or 0)
        if (kind == "openalex_mentions" and cursor == "*" and max_mention_hits
                and hits > max_mention_hits):
            return items, nxt, True, f"alias matched {hits} works; kept top {len(items)}"
        return items, nxt, not items or not nxt, None
    raise ValueError(f"unknown stream kind {kind}")


class LiteratureWorker:
    """Background loop: one unit of work (a resolution or one page) per step."""

    def __init__(self, store: Store, settings: Settings, client_factory=None,
                 http: Http | None = None):
        self.store = store
        self.settings = settings
        self.client_factory = client_factory
        self.http = http or Http(settings)
        self._client = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_error: str | None = None

    # -------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="literature", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                worked = self.step()
            except Exception as exc:  # never let the thread die
                log.exception("literature step failed")
                self.last_error = f"{type(exc).__name__}: {str(exc)[:300]}"
                worked = True
            self._stop.wait(self.settings.lit_interval_sec if worked
                            else self.settings.lit_idle_sec)

    def run_for(self, seconds: float) -> int:
        """Foreground: work until nothing is due or time is up (CLI)."""
        end, steps = time.monotonic() + seconds, 0
        while time.monotonic() < end and self.step():
            steps += 1
            time.sleep(self.settings.lit_interval_sec)
        return steps

    def _llm(self):
        if self._client is None and self.client_factory is not None:
            self._client = self.client_factory(self.settings)
        return self._client

    # -------------------------------------------------------- work
    def step(self) -> bool:
        ds_id = self.store.next_literature_dataset(self.settings.lit_refresh_days)
        if not ds_id:
            return False
        state = self.store.literature_state(ds_id)
        if state is None or state["status"] in ("unresolved", "retry"):
            self.resolve(ds_id)
        elif state["status"] == "complete":
            # Refresh: same descriptors/aliases, cursors reset.
            streams = build_streams(state["descriptors"], state["aliases"],
                                    bool(self.settings.openalex_api_key))
            self.store.save_literature_state(ds_id, status="active", streams=streams,
                                             completed_at=None)
        else:
            self.harvest(ds_id, state)
        return True

    def resolve(self, ds_id: str) -> None:
        ds = self.store.get_dataset(ds_id)
        try:
            cands = gather_candidates(ds, self.http)
        except TransientError as exc:
            # Retried on the next round-robin pass, not after the refresh window.
            self.store.save_literature_state(ds_id, status="retry",
                                             note=f"source unavailable: {exc}")
            return
        client = self._llm()
        try:
            pick = (llm_resolve(client, self.settings, ds, cands) if client
                    else heuristic_resolve(ds, cands))
        except Exception as exc:
            log.warning("LLM resolution failed for %s: %s", ds_id, exc)
            pick = heuristic_resolve(ds, cands)
            pick["note"] = f"heuristic (LLM failed: {type(exc).__name__})"
        by_id = {c["id"]: c for c in cands}
        chosen = [by_id[i] for i in pick["descriptor_ids"]]
        for doi in pick.get("extra_descriptor_dois", []):
            d = norm_doi(doi)
            try:
                body = _epmc_search(self.http, f'DOI:"{d}"', page_size=1)
            except TransientError:
                continue
            for r in (body.get("resultList") or {}).get("result", []):
                chosen.append(from_epmc(r))
        descriptors = []
        for art in chosen:
            aid = save_article(self.store, art)
            self.store.link_article(ds_id, aid, "descriptor", art.get("_why", "llm"))
            descriptors.append({"article_id": aid, "title": art["title"],
                                "epmc": art.get("_epmc"), "openalex_id": art.get("openalex_id")})
        aliases = clean_aliases(pick.get("aliases", []))
        streams = build_streams(descriptors, aliases, bool(self.settings.openalex_api_key))
        self.store.save_literature_state(
            ds_id, status="active" if streams else "unresolved", descriptors=descriptors,
            aliases=aliases, streams=streams, note=pick.get("note"))

    def harvest(self, ds_id: str, state: dict) -> None:
        streams = state["streams"]
        pending = [s for s in streams if not s["done"]]
        if not pending:
            self.store.save_literature_state(ds_id, status="complete",
                                             completed_at=_now())
            return
        # Round-robin inside a dataset too, but cites streams before mentions.
        cites = [s for s in pending if s["kind"].endswith("_cites")]
        stream = (cites or pending)[0]
        descriptor_ids = {d["article_id"] for d in state["descriptors"]}
        try:
            items, nxt, done, note = fetch_page(self.http, stream,
                                                self.settings.lit_max_mention_hits)
        except TransientError as exc:
            stream["error"] = str(exc)[:200]
            stream["failures"] = stream.get("failures", 0) + 1
            if stream["failures"] >= 5:  # give up on this stream until the next refresh
                stream["done"] = True
            self.store.save_literature_state(ds_id, streams=streams)
            return
        relation = "cites" if stream["kind"].endswith("_cites") else "mentions"
        for art in items:
            aid = save_article(self.store, art)
            if aid in descriptor_ids:
                continue
            self.store.link_article(ds_id, aid, relation, stream["kind"],
                                    matched=stream["ref"] if relation == "mentions" else None)
        stream.update(cursor=nxt, done=done, fetched=stream["fetched"] + len(items),
                      error=note, failures=0)
        all_done = all(s["done"] for s in streams)
        self.store.save_literature_state(
            ds_id, streams=streams, status="complete" if all_done else "active",
            completed_at=_now() if all_done else None)


def _now() -> str:
    from .store import now_iso
    return now_iso()
