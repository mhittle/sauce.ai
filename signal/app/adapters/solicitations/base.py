"""Solicitation ingestion (PRD "PlanHub track").

Public procurement / bid boards post commercial construction solicitations,
often with plan + spec PDFs attached. A `SolicitationAdapter` pulls them per
platform and emits NormalizedSolicitation records — the bid-side analogue of
the permit `SourceAdapter`. Dependency-free (stdlib) so normalization is
unit-testable; concrete adapters add their own transport (requests, etc.).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Iterable, Optional

# Reuse the permit-side coercers (stdlib).
from ..base import parse_date, parse_number

# Construction NAICS families: 236 building, 237 heavy/civil, 238 specialty.
CONSTRUCTION_NAICS_PREFIXES = ("236", "237", "238")


@dataclass
class SolicitationDoc:
    name: Optional[str] = None
    url: Optional[str] = None
    doc_type: str = "attachment"   # plans | spec | addendum | attachment | other


@dataclass
class NormalizedSolicitation:
    source_id: str
    title: Optional[str] = None
    agency: Optional[str] = None
    description: Optional[str] = None
    naics: Optional[str] = None
    category: Optional[str] = None
    state: Optional[str] = None
    place_city: Optional[str] = None
    estimated_value: Optional[float] = None
    posted_date: Optional[date] = None
    due_date: Optional[date] = None
    status: Optional[str] = None
    source_url: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    documents: list[SolicitationDoc] = field(default_factory=list)
    raw_payload: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


def is_construction(naics: Optional[str],
                    prefixes: tuple[str, ...] = CONSTRUCTION_NAICS_PREFIXES) -> bool:
    if not naics:
        return False
    return str(naics).strip()[:3] in prefixes


class SolicitationAdapter:
    """Base class. Subclasses implement `fetch_raw` and `parse`."""
    source_type = "base-solicitation"

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}

    def fetch_raw(self, since: Optional[date] = None) -> Iterable[dict]:
        raise NotImplementedError

    def parse(self, record: dict) -> Optional[NormalizedSolicitation]:
        raise NotImplementedError

    def pull(self, since: Optional[date] = None) -> Iterable[NormalizedSolicitation]:
        for record in self.fetch_raw(since):
            norm = self.parse(record)
            if norm is not None:
                yield norm


# re-exported so adapters can coerce without re-importing from the permit base
__all__ = ["NormalizedSolicitation", "SolicitationDoc", "SolicitationAdapter",
           "is_construction", "parse_date", "parse_number",
           "CONSTRUCTION_NAICS_PREFIXES"]
