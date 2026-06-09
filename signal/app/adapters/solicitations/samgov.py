"""SAM.gov Contract Opportunities adapter (federal bids) — the clean public
JSON API that proves the solicitation pipeline (the "Socrata moment" for bids).

API: GET https://api.sam.gov/prod/opportunities/v2/search
  - auth: `api_key` query param (free key from SAM.gov / data.gov)
  - required: postedFrom / postedTo as MM/dd/yyyy (range <= 1 year)
  - paging: limit (<=1000) + offset; response has opportunitiesData[] + totalRecords
  - attachments: each record's `resourceLinks` is a list of download URLs

Construction filtering is done client-side on `naicsCode` (236/237/238) so we
don't depend on the API's NAICS param semantics.
"""
from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Iterable, Optional

import requests

from .base import (CONSTRUCTION_NAICS_PREFIXES, NormalizedSolicitation,
                   SolicitationAdapter, SolicitationDoc, is_construction,
                   parse_date)

API_URL = "https://api.sam.gov/prod/opportunities/v2/search"
MAX_LIMIT = 1000
MAX_RETRIES = 5
DEFAULT_LOOKBACK_DAYS = 30


class SamGovAdapter(SolicitationAdapter):
    source_type = "samgov"

    def __init__(self, api_key: Optional[str] = None,
                 config: Optional[dict] = None,
                 session: Optional[requests.Session] = None):
        super().__init__(config)
        self.api_key = api_key
        self.session = session or requests.Session()
        self.limit = min(int(self.config.get("limit", MAX_LIMIT)), MAX_LIMIT)
        self.naics_prefixes = tuple(
            self.config.get("naics_prefixes", CONSTRUCTION_NAICS_PREFIXES))
        self.state = self.config.get("state")  # optional place-of-performance

    def _params(self, posted_from: date, posted_to: date, offset: int) -> dict:
        p = {
            "api_key": self.api_key,
            "postedFrom": posted_from.strftime("%m/%d/%Y"),
            "postedTo": posted_to.strftime("%m/%d/%Y"),
            "limit": self.limit,
            "offset": offset,
        }
        if self.state:
            p["state"] = self.state
        return p

    def _get_page(self, params: dict) -> dict:
        delay = 1.0
        for attempt in range(MAX_RETRIES):
            try:
                resp = self.session.get(API_URL, params=params,
                                        headers={"Accept": "application/json"},
                                        timeout=60)
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise requests.HTTPError(f"status {resp.status_code}")
                resp.raise_for_status()
                return resp.json()
            except (requests.RequestException, ValueError):
                if attempt == MAX_RETRIES - 1:
                    raise
                time.sleep(delay)
                delay *= 2
        return {}

    def fetch_raw(self, since: Optional[date] = None) -> Iterable[dict]:
        if not self.api_key:
            raise RuntimeError(
                "SAM.gov adapter needs SAMGOV_API_KEY (free from SAM.gov/"
                "data.gov). See signal/INSTALL.md.")
        posted_to = date.today()
        posted_from = since or (posted_to - timedelta(days=DEFAULT_LOOKBACK_DAYS))
        offset = 0
        while True:
            data = self._get_page(self._params(posted_from, posted_to, offset))
            page = data.get("opportunitiesData") or []
            if not page:
                return
            yield from page
            offset += self.limit
            total = data.get("totalRecords")
            if len(page) < self.limit or (total is not None and offset >= total):
                return

    def parse(self, record: dict) -> Optional[NormalizedSolicitation]:
        source_id = record.get("noticeId")
        if not source_id:
            return None
        naics = record.get("naicsCode")
        if not is_construction(naics, self.naics_prefixes):
            return None

        place = record.get("placeOfPerformance") or {}
        state = (place.get("state") or {}).get("code")
        city = (place.get("city") or {}).get("name")
        docs = [SolicitationDoc(name=str(u).rstrip("/").split("/")[-1], url=u)
                for u in (record.get("resourceLinks") or []) if u]

        return NormalizedSolicitation(
            source_id=source_id,
            title=record.get("title"),
            agency=record.get("fullParentPathName"),
            description=record.get("description"),  # often a follow-up API link
            naics=naics,
            category=record.get("classificationCode"),
            state=state,
            place_city=city,
            posted_date=parse_date(record.get("postedDate")),
            due_date=parse_date(record.get("responseDeadLine")),
            status=record.get("type"),
            source_url=record.get("uiLink"),
            documents=docs,
            raw_payload=record,
        )
