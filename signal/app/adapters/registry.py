"""Adapter registry: route a jurisdiction to its SourceAdapter.

Keyed by jurisdiction.source_type. New platform types (arcgis, accela,
etrakit, cityview) register here as they're built (PRD §6, phased).
"""
from __future__ import annotations

from typing import Optional

from .base import SourceAdapter
from .paid import PaidApiAdapter
from .socrata import SocrataAdapter

_REGISTRY: dict[str, type[SourceAdapter]] = {
    SocrataAdapter.source_type: SocrataAdapter,
    PaidApiAdapter.source_type: PaidApiAdapter,
}


def register(adapter_cls: type[SourceAdapter]) -> None:
    _REGISTRY[adapter_cls.source_type] = adapter_cls


def supported_source_types() -> list[str]:
    return sorted(_REGISTRY)


def build_adapter(jurisdiction: dict, *, socrata_token: Optional[str] = None,
                  paid_api_key: Optional[str] = None) -> SourceAdapter:
    source_type = jurisdiction.get("source_type", "socrata")
    cls = _REGISTRY.get(source_type)
    if cls is None:
        raise ValueError(
            f"No adapter registered for source_type={source_type!r}. "
            f"Supported: {supported_source_types()}"
        )
    if cls is SocrataAdapter:
        return cls(jurisdiction, app_token=socrata_token)
    if cls is PaidApiAdapter:
        return cls(jurisdiction, api_key=paid_api_key)
    return cls(jurisdiction)
