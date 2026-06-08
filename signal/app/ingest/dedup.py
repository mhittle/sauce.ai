"""Cross-source project dedup (PRD §6, §7 project_id, §8 dedup_confidence).

Permits collapse into one Project by, in priority order:
  1. parcel/APN (strongest),
  2. normalized street address,
  3. source permit number (weakest — same permit re-pulled).

Pure functions so the matching logic is unit-testable without a DB.
"""
from __future__ import annotations

import re
from typing import Optional

_DIRECTIONS = {"north": "n", "south": "s", "east": "e", "west": "w",
               "northeast": "ne", "northwest": "nw", "southeast": "se",
               "southwest": "sw"}
_SUFFIXES = {"street": "st", "avenue": "ave", "boulevard": "blvd",
             "road": "rd", "drive": "dr", "lane": "ln", "court": "ct",
             "place": "pl", "parkway": "pkwy", "highway": "hwy",
             "suite": "ste", "building": "bldg"}


def normalize_address(address: Optional[str]) -> str:
    if not address:
        return ""
    s = address.lower()
    s = re.sub(r"[.,#]", " ", s)
    tokens = []
    for tok in s.split():
        tok = _DIRECTIONS.get(tok, tok)
        tok = _SUFFIXES.get(tok, tok)
        tokens.append(tok)
    return re.sub(r"\s+", " ", " ".join(tokens)).strip()


def normalize_apn(apn: Optional[str]) -> str:
    if not apn:
        return ""
    return re.sub(r"[^a-z0-9]", "", apn.lower())


def dedup_key(permit: dict) -> tuple[str, str]:
    """Return (key_type, key_value). Falls back through APN -> address -> id."""
    apn = normalize_apn(permit.get("parcel_apn"))
    if apn:
        return ("apn", apn)
    addr = normalize_address(permit.get("address"))
    if addr:
        return ("address", addr)
    return ("permit", str(permit.get("permit_id") or "").strip())


def dedup_confidence(key_type: str) -> float:
    return {"apn": 0.95, "address": 0.8, "permit": 0.5}.get(key_type, 0.5)


def group_permits(permits: list[dict]) -> dict[tuple[str, str], list[dict]]:
    """Group a batch of permits into candidate projects by dedup key."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for p in permits:
        groups.setdefault(dedup_key(p), []).append(p)
    return groups
