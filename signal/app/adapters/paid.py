"""Paid permit-API adapter stub (PRD §6.4, §13.2).

Wired behind the SAME SourceAdapter interface so a commercial source (e.g.
Shovels.ai) can accelerate national coverage later without touching the
ingest pipeline. Disabled by default: a jurisdiction only routes here when
its source_type == "paid" AND a SIGNAL_PAID_API_KEY is configured.

Phase 0 intentionally ships no live calls — fetch_raw raises unless an
api_key is present, so accidental dispatch can't silently cost money.
"""
from __future__ import annotations

from datetime import date
from typing import Iterable, Optional

from .base import SourceAdapter


class PaidApiAdapter(SourceAdapter):
    source_type = "paid"

    def __init__(self, jurisdiction: dict, api_key: Optional[str] = None,
                 session=None):
        super().__init__(jurisdiction)
        self.api_key = api_key
        self.session = session

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def fetch_raw(self, since: Optional[date] = None) -> Iterable[dict]:
        if not self.enabled:
            raise RuntimeError(
                "PaidApiAdapter is disabled: set SIGNAL_PAID_API_KEY and "
                "implement the concrete client before routing a jurisdiction "
                "to source_type='paid'. See PRD §13.2 (build-vs-buy)."
            )
        # Concrete vendor client goes here (Shovels.ai / Dodge / etc.).
        # Map vendor pagination -> raw dicts; field_map handles normalization.
        raise NotImplementedError("Concrete paid-API client not yet built.")
