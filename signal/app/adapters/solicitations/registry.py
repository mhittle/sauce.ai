"""Solicitation adapter registry — route a source_type to its adapter."""
from __future__ import annotations

from typing import Optional

from .base import SolicitationAdapter
from .samgov import SamGovAdapter
from .scaffolds import SCAFFOLD_ADAPTERS

_REGISTRY: dict[str, type[SolicitationAdapter]] = {
    SamGovAdapter.source_type: SamGovAdapter,
    **{cls.source_type: cls for cls in SCAFFOLD_ADAPTERS},
}


def register(adapter_cls: type[SolicitationAdapter]) -> None:
    _REGISTRY[adapter_cls.source_type] = adapter_cls


def supported_source_types() -> list[str]:
    return sorted(_REGISTRY)


def build_solicitation_adapter(source_type: str, *,
                               samgov_api_key: Optional[str] = None,
                               config: Optional[dict] = None) -> SolicitationAdapter:
    cls = _REGISTRY.get(source_type)
    if cls is None:
        raise ValueError(
            f"No solicitation adapter for source_type={source_type!r}. "
            f"Supported: {supported_source_types()}")
    if cls is SamGovAdapter:
        return cls(api_key=samgov_api_key, config=config)
    return cls(config=config)
