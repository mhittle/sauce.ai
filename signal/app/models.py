"""SQLAlchemy ORM models mirroring seed/schema.sql.

Geometry and vector columns are intentionally NOT mapped here — they're read
and written via raw SQL where spatial / pgvector operators are needed, which
keeps the ORM free of geoalchemy2/pgvector type plumbing.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (BigInteger, Boolean, Date, DateTime, ForeignKey,
                        Integer, Numeric, String, Text, func)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Jurisdiction(Base):
    __tablename__ = "jurisdictions"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    slug: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String)
    state: Mapped[str | None] = mapped_column(String, nullable=True)
    county: Mapped[str | None] = mapped_column(String, nullable=True)
    source_type: Mapped[str] = mapped_column(String, default="socrata")
    platform_domain: Mapped[str | None] = mapped_column(String, nullable=True)
    dataset_id: Mapped[str | None] = mapped_column(String, nullable=True)
    field_map: Mapped[dict] = mapped_column(JSONB, default=dict)
    adapter_config: Mapped[dict] = mapped_column(JSONB, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_good_pull: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    known_lag_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    jurisdiction_id: Mapped[int | None] = mapped_column(ForeignKey("jurisdictions.id"), nullable=True)
    primary_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    parcel_apn: Mapped[str | None] = mapped_column(String, nullable=True)
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    value_tier: Mapped[str | None] = mapped_column(String, nullable=True)
    lead_score: Mapped[float] = mapped_column(Numeric(8, 3), default=0)
    status: Mapped[str] = mapped_column(String, default="new")
    dedup_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    scope_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_classified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    crm_id: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Permit(Base):
    __tablename__ = "permits"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    jurisdiction_id: Mapped[int] = mapped_column(ForeignKey("jurisdictions.id"))
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    permit_id: Mapped[str] = mapped_column(String)
    source_type: Mapped[str] = mapped_column(String, default="socrata")
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    permit_type: Mapped[str | None] = mapped_column(String, nullable=True)
    permit_subtype: Mapped[str | None] = mapped_column(String, nullable=True)
    work_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    valuation: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    application_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiration_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_status_change: Mapped[date | None] = mapped_column(Date, nullable=True)
    final_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    parcel_apn: Mapped[str | None] = mapped_column(String, nullable=True)
    owner_name: Mapped[str | None] = mapped_column(String, nullable=True)
    applicant: Mapped[str | None] = mapped_column(String, nullable=True)
    contractor_name: Mapped[str | None] = mapped_column(String, nullable=True)
    contractor_license: Mapped[str | None] = mapped_column(String, nullable=True)
    use_type: Mapped[str | None] = mapped_column(String, nullable=True)
    occupancy: Mapped[str | None] = mapped_column(String, nullable=True)
    sqft: Mapped[float | None] = mapped_column(Numeric(12, 1), nullable=True)
    units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fees: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SignalCatalog(Base):
    __tablename__ = "signal_catalog"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    label: Mapped[str] = mapped_column(String)
    tier: Mapped[str] = mapped_column(String)
    datatype: Mapped[str] = mapped_column(String)
    how_derived: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_facet: Mapped[bool] = mapped_column(Boolean, default=True)


class ProjectSignal(Base):
    __tablename__ = "project_signals"
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    signal_id: Mapped[str] = mapped_column(ForeignKey("signal_catalog.id"), primary_key=True)
    value_bool: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    value_num: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Rule(Base):
    __tablename__ = "rules"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    owner_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    profile: Mapped[str] = mapped_column(String, default="default")
    weights: Mapped[dict] = mapped_column(JSONB, default=dict)
    threshold: Mapped[float] = mapped_column(Numeric(8, 3), default=0)
    filters: Mapped[dict] = mapped_column(JSONB, default=dict)
    digest_recipients: Mapped[list] = mapped_column(JSONB, default=list)
    send_time: Mapped[str | None] = mapped_column(String, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class IngestRun(Base):
    __tablename__ = "ingest_runs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    jurisdiction_id: Mapped[int | None] = mapped_column(ForeignKey("jurisdictions.id"), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String, default="running")
    permits_fetched: Mapped[int] = mapped_column(Integer, default=0)
    permits_upserted: Mapped[int] = mapped_column(Integer, default=0)
    projects_touched: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
