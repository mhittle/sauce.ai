"""Pydantic response/request models for the API."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel


class SignalDefOut(BaseModel):
    id: str
    label: str
    tier: str
    datatype: str
    how_derived: str
    is_facet: bool


class ProjectOut(BaseModel):
    id: int
    primary_address: Optional[str] = None
    jurisdiction: Optional[str] = None
    category: Optional[str] = None
    value_tier: Optional[str] = None
    lead_score: float = 0
    status: str = "new"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    crm_id: Optional[str] = None
    updated_at: Optional[datetime] = None


class ProjectListOut(BaseModel):
    total: int
    items: list[ProjectOut]


class PermitOut(BaseModel):
    permit_id: str
    permit_type: Optional[str] = None
    work_description: Optional[str] = None
    valuation: Optional[float] = None
    status: Optional[str] = None
    issue_date: Optional[date] = None
    expiration_date: Optional[date] = None
    contractor_name: Optional[str] = None
    source_url: Optional[str] = None


class ProjectDetailOut(ProjectOut):
    permits: list[PermitOut] = []
    signals: dict[str, Any] = {}
    why_flagged: list[dict] = []


class SolicitationOut(BaseModel):
    id: int
    source_type: str
    title: Optional[str] = None
    agency: Optional[str] = None
    naics: Optional[str] = None
    state: Optional[str] = None
    place_city: Optional[str] = None
    estimated_value: Optional[float] = None
    posted_date: Optional[date] = None
    due_date: Optional[date] = None
    status: Optional[str] = None
    source_url: Optional[str] = None
    doc_count: int = 0


class SolicitationListOut(BaseModel):
    total: int
    items: list[SolicitationOut]


class SolicitationDocOut(BaseModel):
    name: Optional[str] = None
    url: str
    doc_type: str = "attachment"


class SolicitationDetailOut(SolicitationOut):
    description: Optional[str] = None
    documents: list[SolicitationDocOut] = []


class JurisdictionOut(BaseModel):
    slug: str
    name: str
    state: Optional[str] = None
    source_type: str
    active: bool
    last_good_pull: Optional[datetime] = None
    known_lag_days: Optional[int] = None
    staleness_days: Optional[int] = None
