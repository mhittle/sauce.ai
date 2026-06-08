"""Generic Socrata / SODA adapter (PRD §6.1).

One adapter, parameterized per dataset (domain + dataset id + field_map),
unlocks every Socrata / Tyler "Data & Insights" city at once. A free app
token lifts rate limits; pass it via SOCRATA_APP_TOKEN.

Pagination via $limit/$offset; optional incremental pull via a date column
in adapter_config["updated_field"]. Exponential backoff on transient errors
(PRD §16).
"""
from __future__ import annotations

import time
from datetime import date
from typing import Iterable, Optional

import requests

from .base import SourceAdapter

DEFAULT_PAGE_SIZE = 1000
MAX_RETRIES = 5


class SocrataAdapter(SourceAdapter):
    source_type = "socrata"

    def __init__(self, jurisdiction: dict, app_token: Optional[str] = None,
                 session: Optional[requests.Session] = None):
        super().__init__(jurisdiction)
        self.app_token = app_token
        self.session = session or requests.Session()
        self.page_size = int(self.config.get("page_size", DEFAULT_PAGE_SIZE))

    @property
    def base_url(self) -> str:
        domain = self.jurisdiction["platform_domain"]
        dataset = self.jurisdiction["dataset_id"]
        return f"https://{domain}/resource/{dataset}.json"

    def _headers(self) -> dict:
        return {"X-App-Token": self.app_token} if self.app_token else {}

    def _where_clause(self, since: Optional[date]) -> Optional[str]:
        updated_field = self.config.get("updated_field")
        if since and updated_field:
            return f"{updated_field} >= '{since.isoformat()}T00:00:00'"
        return None

    def _get_page(self, offset: int, where: Optional[str]) -> list[dict]:
        params = {"$limit": self.page_size, "$offset": offset,
                  "$order": self.config.get("order_field", ":id")}
        if where:
            params["$where"] = where
        delay = 1.0
        for attempt in range(MAX_RETRIES):
            try:
                resp = self.session.get(self.base_url, params=params,
                                        headers=self._headers(), timeout=60)
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise requests.HTTPError(f"status {resp.status_code}")
                resp.raise_for_status()
                return resp.json()
            except (requests.RequestException, ValueError):
                if attempt == MAX_RETRIES - 1:
                    raise
                time.sleep(delay)
                delay *= 2
        return []

    def fetch_raw(self, since: Optional[date] = None) -> Iterable[dict]:
        where = self._where_clause(since)
        offset = 0
        while True:
            page = self._get_page(offset, where)
            if not page:
                return
            yield from page
            if len(page) < self.page_size:
                return
            offset += self.page_size
