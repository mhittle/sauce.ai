"""Bonfire (Euna Solutions) public-opportunities adapter — the lighter CA path.

California's statewide register (Cal eProcure / CSCR) is a PeopleSoft SPA that
needs a headless browser, and PlanetBids bot-walls automation. But a large
number of CA agencies post on **Bonfire**, which exposes a clean, public JSON
endpoint that plain requests can read:

    GET https://<agency>.bonfirehub.com/PublicPortal/getOpenPublicOpportunitiesSectionData
    -> {"success", "message", "payload": {"projects": {id: {...}}, "departments": {id: {...}}}}

So one adapter unlocks many CA (and national) agencies — the "Socrata moment"
for the Bonfire family — by listing each agency's open opportunities. Verified
live 2026-06-30 against ventura/wrd/calmhsa.

Scope note: this lists OPPORTUNITIES (title, dept, close date, ref id, link).
The per-opportunity **document** pages (`/opportunities/<id>`) are Cloudflare-
challenged, so bid PDFs aren't bot-downloadable here (unlike SAM.gov's public
resourceLinks) — discovery + triage now; documents are a later item. No NAICS
on Bonfire, so we ingest all open opportunities and let
`classify_solicitations` score cabinetry relevance.
"""
from __future__ import annotations

from datetime import date
from typing import Iterable, Optional

import requests

from .base import (NormalizedSolicitation, SolicitationAdapter, parse_date)

DATA_PATH = "/PublicPortal/getOpenPublicOpportunitiesSectionData"
PORTAL_PATH = "/portal/?tab=openOpportunities"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Verified-live CA agency subdomains. Add more (any `<x>.bonfirehub.com`) here
# or override via config={"agencies": [...]}.
DEFAULT_AGENCIES = ("ventura", "wrd", "calmhsa")


class BonfireAdapter(SolicitationAdapter):
    source_type = "bonfire"

    def __init__(self, config: Optional[dict] = None,
                 session: Optional[requests.Session] = None):
        super().__init__(config)
        self.agencies = tuple(self.config.get("agencies", DEFAULT_AGENCIES))
        self.default_state = self.config.get("state", "CA")
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": UA,
                                     "X-Requested-With": "XMLHttpRequest"})

    def _fetch_agency(self, agency: str) -> Iterable[dict]:
        base = f"https://{agency}.bonfirehub.com"
        # Seed cookies from the portal page, then pull the public JSON.
        self.session.get(base + PORTAL_PATH, timeout=45)
        resp = self.session.get(base + DATA_PATH, timeout=45)
        resp.raise_for_status()
        # Bonfire is behind Cloudflare. From a flagged IP it can answer a bot
        # *challenge* (HTML, 403/429/503, or cf-mitigated) instead of JSON —
        # fail loudly so the IngestRun records it rather than parsing garbage.
        ct = resp.headers.get("content-type", "")
        if resp.headers.get("cf-mitigated") or "json" not in ct.lower():
            raise RuntimeError(
                f"bonfire[{agency}]: expected JSON, got {ct or 'no-ctype'} "
                f"(status {resp.status_code}) — likely a Cloudflare bot "
                f"challenge on this egress IP. cf-ray="
                f"{resp.headers.get('cf-ray')}")
        payload = (resp.json() or {}).get("payload") or {}
        projects = payload.get("projects") or {}
        departments = payload.get("departments") or {}
        for proj in projects.values():
            if not isinstance(proj, dict):
                continue
            dept = departments.get(str(proj.get("DepartmentID")), {})
            yield {**proj, "_agency": agency,
                   "_department": dept.get("DepartmentName"),
                   "_base": base}

    def fetch_raw(self, since: Optional[date] = None) -> Iterable[dict]:
        for agency in self.agencies:
            try:
                yield from self._fetch_agency(agency)
            except requests.RequestException:
                # One bad agency shouldn't sink the run (logged at the ingest
                # boundary via the IngestRun); skip and continue.
                continue

    def parse(self, record: dict) -> Optional[NormalizedSolicitation]:
        pid = record.get("ProjectID")
        agency = record.get("_agency")
        if not pid or not agency:
            return None
        base = record.get("_base") or f"https://{agency}.bonfirehub.com"
        return NormalizedSolicitation(
            source_id=f"{agency}-{pid}",
            title=record.get("ProjectName"),
            agency=record.get("_department") or agency,
            category=record.get("ReferenceID"),
            state=self.default_state,
            due_date=parse_date(record.get("DateClose")),
            status="open",
            source_url=f"{base}{PORTAL_PATH}&id={pid}",
            raw_payload=record,
        )
