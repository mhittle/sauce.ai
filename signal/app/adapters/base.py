"""SourceAdapter interface + the canonical normalized record.

Every adapter has one job: pull permits for a jurisdiction and emit
NormalizedPermit records mapped onto the canonical schema (PRD §6, §7).
A jurisdiction's `field_map` (canonical_field -> source_column) drives the
mapping so the same generic adapter serves many portals.

This module is intentionally dependency-free (stdlib only) so the
normalization core can be unit-tested without a DB or network.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Any, Iterable, Optional

# Canonical fields an adapter may populate. The field_map keys are a subset.
CANONICAL_FIELDS = (
    "permit_id", "permit_type", "permit_subtype", "work_description",
    "valuation", "status", "application_date", "issue_date",
    "expiration_date", "last_status_change", "final_date", "address",
    "latitude", "longitude", "parcel_apn", "owner_name", "applicant",
    "contractor_name", "contractor_license", "use_type", "occupancy",
    "sqft", "units", "fees", "source_url",
)

_DATE_FORMATS = (
    "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%Y %H:%M:%S %p", "%m/%d/%Y %I:%M:%S %p",
    "%m/%d/%Y %I:%M %p", "%m/%d/%Y %H:%M",   # CivicPlus "6/10/2026 2:00 PM"
)


def parse_date(value: Any) -> Optional[date]:
    """Best-effort parse of the many date formats portals emit."""
    if value in (None, "", "null"):
        return None
    if isinstance(value, (date, datetime)):
        return value.date() if isinstance(value, datetime) else value
    s = str(value).strip()
    try:                       # ISO 8601 incl. tz offsets (e.g. 2026-06-15T17:00:00-04:00)
        return datetime.fromisoformat(s).date()
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_number(value: Any) -> Optional[float]:
    if value in (None, "", "null"):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r"[^0-9.\-]", "", str(value))
    if cleaned in ("", "-", "."):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_int(value: Any) -> Optional[int]:
    n = parse_number(value)
    return int(n) if n is not None else None


@dataclass
class NormalizedPermit:
    """One source record mapped onto the canonical schema."""
    permit_id: str
    permit_type: Optional[str] = None
    permit_subtype: Optional[str] = None
    work_description: Optional[str] = None
    valuation: Optional[float] = None
    status: Optional[str] = None
    application_date: Optional[date] = None
    issue_date: Optional[date] = None
    expiration_date: Optional[date] = None
    last_status_change: Optional[date] = None
    final_date: Optional[date] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    parcel_apn: Optional[str] = None
    owner_name: Optional[str] = None
    applicant: Optional[str] = None
    contractor_name: Optional[str] = None
    contractor_license: Optional[str] = None
    use_type: Optional[str] = None
    occupancy: Optional[str] = None
    sqft: Optional[float] = None
    units: Optional[int] = None
    fees: Optional[float] = None
    source_url: Optional[str] = None
    raw_payload: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


# Per-canonical-field coercion applied after the raw value is pulled.
_COERCE = {
    "valuation": parse_number, "fees": parse_number, "sqft": parse_number,
    "latitude": parse_number, "longitude": parse_number, "units": parse_int,
    "application_date": parse_date, "issue_date": parse_date,
    "expiration_date": parse_date, "last_status_change": parse_date,
    "final_date": parse_date,
}


def _dig(record: dict, source_key: str) -> Any:
    """Resolve a source column, including Socrata's nested `location` dict."""
    if source_key in record:
        return record[source_key]
    if "." in source_key:           # e.g. location.latitude
        cur: Any = record
        for part in source_key.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return None
        return cur
    return None


def normalize_record(record: dict, field_map: dict) -> Optional[NormalizedPermit]:
    """Map one raw source record onto a NormalizedPermit via field_map.

    field_map is {canonical_field: source_column}. Records missing a usable
    permit_id are dropped (we can't dedup or upsert them).
    """
    values: dict[str, Any] = {}
    for canonical, source_key in field_map.items():
        if canonical not in CANONICAL_FIELDS:
            continue
        raw = _dig(record, source_key)
        coerce = _COERCE.get(canonical)
        values[canonical] = coerce(raw) if coerce else (
            str(raw).strip() if raw not in (None, "") else None
        )

    permit_id = values.get("permit_id")
    if not permit_id:
        return None

    values["raw_payload"] = record
    known = {k: v for k, v in values.items()
             if k in NormalizedPermit.__dataclass_fields__}
    return NormalizedPermit(**known)


class SourceAdapter:
    """Base class. Subclasses pull raw records and yield NormalizedPermit.

    Contract:
      * `fetch_raw(since)` returns an iterable of raw source dicts.
      * `pull(since)` normalizes them through the jurisdiction's field_map.
    Subclasses normally only implement `fetch_raw`.
    """
    source_type = "base"

    def __init__(self, jurisdiction: dict):
        self.jurisdiction = jurisdiction
        self.field_map = jurisdiction.get("field_map") or {}
        self.config = jurisdiction.get("adapter_config") or {}

    def fetch_raw(self, since: Optional[date] = None) -> Iterable[dict]:
        raise NotImplementedError

    def pull(self, since: Optional[date] = None) -> Iterable[NormalizedPermit]:
        for record in self.fetch_raw(since):
            norm = normalize_record(record, self.field_map)
            if norm is not None:
                yield norm
