"""Signal catalog endpoint — drives the dashboard's facet sidebar (PRD §10).

Served straight from the in-code registry (the source of truth), so facets
exist even before any ingest has run.
"""
from __future__ import annotations

from fastapi import APIRouter

from ..schemas import SignalDefOut
from ..signals.registry import SIGNALS

router = APIRouter(prefix="/api/signals", tags=["signals"])


@router.get("", response_model=list[SignalDefOut])
def list_signals(tier: str | None = None, facets_only: bool = False):
    out = SIGNALS
    if tier:
        out = [s for s in out if s.tier == tier]
    if facets_only:
        out = [s for s in out if s.is_facet]
    return [SignalDefOut(**s.__dict__) for s in out]
