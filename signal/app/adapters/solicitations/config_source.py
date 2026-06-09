"""Config-driven procurement-source adapters — the reusable core of the
adapter library (PRD PlanHub track).

Instead of hand-writing a scraper per agency, a source is a CONFIG entry in
seed/procurement_sources.json (the bid-board analogue of jurisdictions.json):
a platform type (`json` | `html`), a list URL, and a field map. Two generic
adapters consume that config:

  * JsonConfigAdapter — for SPA-backed portals exposing a JSON list endpoint
    (Bonfire/OpenGov-style). Stdlib JSON + dotted field paths.
  * HtmlConfigAdapter — for server-rendered bid lists. CSS row + field
    selectors via BeautifulSoup.

Adding a state/county/local source = a config entry + tuning selectors with
`jobs/validate_procurement_source.py` against the live page (the same
"validate on first pull" loop we use for permit field maps).
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import time
from datetime import date
from typing import Any, Iterable, Optional
from urllib.parse import urljoin

import requests

_SOURCES_PATH = (pathlib.Path(__file__).resolve().parents[3]
                 / "seed" / "procurement_sources.json")


def load_sources() -> list[dict]:
    if not _SOURCES_PATH.exists():
        return []
    return json.loads(_SOURCES_PATH.read_text())


def get_source(slug: str) -> Optional[dict]:
    return next((s for s in load_sources() if s.get("slug") == slug), None)

from .base import (NormalizedSolicitation, SolicitationAdapter, SolicitationDoc,
                   parse_date, parse_number)

MAX_RETRIES = 4

_CANONICAL = ("source_id", "title", "agency", "description", "naics",
              "category", "state", "place_city", "estimated_value",
              "posted_date", "due_date", "status", "source_url")


def _get(session, url: str, timeout: int = 45):
    delay = 1.0
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, timeout=timeout,
                               headers={"User-Agent": "sauce.ai-signal/0.1"})
            if resp.status_code == 429 or resp.status_code >= 500:
                raise requests.HTTPError(f"status {resp.status_code}")
            resp.raise_for_status()
            return resp
        except requests.RequestException:
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(delay)
            delay *= 2


def _dig(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    return cur


class ConfigSolicitationAdapter(SolicitationAdapter):
    """Shared parse(): an extracted {canonical_field: str} dict -> Normalized."""
    source_type = "config"

    def __init__(self, source_cfg: dict, session: Optional[requests.Session] = None):
        super().__init__(source_cfg.get("config") or {})
        self.source_cfg = source_cfg
        self.list_url = source_cfg["list_url"]
        self.default_state = source_cfg.get("state")
        self.base_url = self.config.get("base_url", self.list_url)
        self.session = session or requests.Session()

    def parse(self, record: dict) -> Optional[NormalizedSolicitation]:
        d = {k: record.get(k) for k in _CANONICAL}
        source_id = d.get("source_id") or d.get("source_url")
        if not source_id:
            return None
        if not d.get("source_id"):
            d["source_id"] = hashlib.sha1(
                str(source_id).encode()).hexdigest()[:16]
        docs = [SolicitationDoc(name=x.get("name"), url=x["url"],
                                doc_type=x.get("doc_type", "attachment"))
                for x in (record.get("documents") or []) if x.get("url")]
        return NormalizedSolicitation(
            source_id=str(d["source_id"]),
            title=d.get("title"), agency=d.get("agency"),
            description=d.get("description"), naics=d.get("naics"),
            category=d.get("category"),
            state=d.get("state") or self.default_state,
            place_city=d.get("place_city"),
            estimated_value=parse_number(d.get("estimated_value")),
            posted_date=parse_date(d.get("posted_date")),
            due_date=parse_date(d.get("due_date")),
            status=d.get("status"), source_url=d.get("source_url"),
            documents=docs, raw_payload=record)


class JsonConfigAdapter(ConfigSolicitationAdapter):
    source_type = "json"

    def fetch_raw(self, since: Optional[date] = None) -> Iterable[dict]:
        records_path = self.config.get("records_path", "")
        fields: dict = self.config["fields"]
        docs_cfg = self.config.get("documents")
        data = _get(self.session, self.list_url).json()
        records = _dig(data, records_path) if records_path else data
        for rec in records or []:
            out = {canon: _dig(rec, path) for canon, path in fields.items()}
            if docs_cfg:
                docs = _dig(rec, docs_cfg.get("path", "")) or []
                out["documents"] = [
                    {"name": _dig(x, docs_cfg.get("name", "")),
                     "url": _dig(x, docs_cfg.get("url", ""))}
                    for x in docs if isinstance(x, dict)]
            yield out


def _guess_doc_type(name: str) -> str:
    n = (name or "").lower()
    if "plan" in n or "drawing" in n:
        return "plans"
    if "spec" in n:
        return "spec"
    if "addend" in n or "amend" in n:
        return "addendum"
    return "attachment"


class HtmlConfigAdapter(ConfigSolicitationAdapter):
    source_type = "html"

    def _fetch_documents(self, url: str, detail_cfg: dict) -> list[dict]:
        """Fetch a solicitation's detail page and extract attachment links
        (the actual bid package / plans). Failures degrade to []."""
        from bs4 import BeautifulSoup
        spec = detail_cfg.get("documents")
        if not spec or not url:
            return []
        try:
            html = _get(self.session, url).text
        except requests.RequestException:
            return []
        soup = BeautifulSoup(html, "html.parser")
        docs = []
        for a in soup.select(spec["selector"]):
            href = a.get("href")
            if href:
                name = a.get_text(" ", strip=True)
                docs.append({"name": name, "url": urljoin(self.base_url, href),
                             "doc_type": _guess_doc_type(name)})
        return docs

    def _field(self, row, spec: dict) -> Optional[str]:
        el = row.select_one(spec["selector"]) if spec.get("selector") else row
        if el is None:
            return None
        attr = spec.get("attr", "text")
        val = el.get_text(" ", strip=True) if attr == "text" else el.get(attr)
        if val and attr in ("href", "src"):
            val = urljoin(self.base_url, val)
        if val and spec.get("regex"):
            m = re.search(spec["regex"], val)
            val = m.group(1) if m else None
        return val

    def fetch_raw(self, since: Optional[date] = None) -> Iterable[dict]:
        from bs4 import BeautifulSoup
        fields: dict = self.config["fields"]
        docs_cfg = self.config.get("documents")     # documents on the list row
        detail_cfg = self.config.get("detail")      # documents on the detail page
        html = _get(self.session, self.list_url).text
        soup = BeautifulSoup(html, "html.parser")
        for row in soup.select(self.config["row_selector"]):
            out = {canon: self._field(row, spec) for canon, spec in fields.items()}
            if docs_cfg:
                out["documents"] = [
                    {"name": a.get_text(" ", strip=True),
                     "url": urljoin(self.base_url, a.get("href"))}
                    for a in row.select(docs_cfg["selector"]) if a.get("href")]
            elif detail_cfg and out.get("source_url"):
                out["documents"] = self._fetch_documents(out["source_url"], detail_cfg)
            yield out


def civicplus_config(domain: str) -> dict:
    """The validated CivicPlus `Bids.aspx` selectors. Identical across every
    CivicPlus municipality, so a source only needs its domain."""
    return {
        "base_url": f"https://{domain}/",
        "row_selector": ".listItemsRow.bid",
        "fields": {
            "title": {"selector": ".bidTitle a", "attr": "text"},
            "source_url": {"selector": ".bidTitle a", "attr": "href"},
            "source_id": {"selector": ".bidTitle a", "attr": "href",
                          "regex": r"bidID=(\d+)"},
            "status": {"selector": ".bidStatus div:nth-of-type(2) span",
                       "attr": "text"},
            "due_date": {"selector": ".bidStatus div:nth-of-type(2) span:nth-of-type(2)",
                         "attr": "text"},
        },
        # Bid package (plans/specs/addenda) lives on each bid's detail page.
        "detail": {"documents": {
            "selector": '.relatedDocuments a[href*="DocumentCenter"]'}},
    }


def civicplus_list_url(domain: str) -> str:
    return f"https://{domain}/Bids.aspx?CatID=showStatus&txtSort=Category&Status=open"


def build_config_adapter(source_cfg: dict,
                         session: Optional[requests.Session] = None
                         ) -> ConfigSolicitationAdapter:
    platform = source_cfg.get("platform", "json")
    if platform == "civicplus":
        # Compact form: entry carries only `domain`; synthesize the config.
        domain = source_cfg["domain"]
        merged = dict(source_cfg)
        merged.setdefault("list_url", civicplus_list_url(domain))
        merged["config"] = civicplus_config(domain)
        return HtmlConfigAdapter(merged, session)
    if platform == "json":
        return JsonConfigAdapter(source_cfg, session)
    if platform == "html":
        return HtmlConfigAdapter(source_cfg, session)
    raise ValueError(f"Unknown procurement platform: {platform!r} "
                     f"(expected 'civicplus', 'json', or 'html')")
