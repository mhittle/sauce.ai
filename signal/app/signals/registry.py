"""The signal registry — the source of truth for the signal catalog (PRD §8).

Every signal is defined once here with (id, label, tier, datatype,
how_derived, is_facet). This drives two things automatically (PRD §8 design
requirement):
  1. The signal_catalog DB rows (seed via jobs/seed_signals.py).
  2. Which facets the dashboard exposes and which inputs a rule can weight.

Adding a signal = adding a SignalDef here. No schema change required, because
values live EAV-style in project_signals.

Tiers: ingested (straight from the record), derived (computed by us — the
differentiation), enrichment (external sources, later phases).
Datatypes: bool | number | category | text | geo.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SignalDef:
    id: str
    label: str
    tier: str          # ingested | derived | enrichment
    datatype: str      # bool | number | category | text | geo
    how_derived: str
    is_facet: bool = True


SIGNALS: tuple[SignalDef, ...] = (
    # ---- A) Ingested -------------------------------------------------------
    SignalDef("permit_type", "Permit type / subtype", "ingested", "category",
              "from record"),
    SignalDef("work_description", "Work / scope description", "ingested", "text",
              "from record", is_facet=False),
    SignalDef("valuation", "Project valuation ($)", "ingested", "number",
              "from record"),
    SignalDef("status", "Permit status", "ingested", "category", "from record"),
    SignalDef("use_type", "Use / occupancy / building type", "ingested",
              "category", "from record"),
    SignalDef("sqft", "Square footage", "ingested", "number", "from record"),
    SignalDef("units", "Unit count", "ingested", "number", "from record"),
    SignalDef("contractor_name", "Contractor of record", "ingested", "category",
              "from record"),
    SignalDef("jurisdiction", "Jurisdiction (city/county/state)", "ingested",
              "category", "from record"),

    # ---- B) Derived (the differentiation) ---------------------------------
    SignalDef("is_commercial", "Commercial vs residential", "derived", "bool",
              "rules + LLM over use_type + scope"),
    SignalDef("category", "Project category", "derived", "category",
              "classify scope/use (hospitality/office/retail/...)"),
    SignalDef("value_tier", "Value tier", "derived", "category",
              "bucketed from valuation"),
    SignalDef("cabinet_relevance", "Cabinet-relevance score", "derived",
              "number", "semantic match on scope (casework/millwork/FF&E)"),
    SignalDef("casework_intensity", "Casework intensity", "derived", "category",
              "scope analysis"),
    SignalDef("stage", "Stage / timeline position", "derived", "category",
              "from status + dates"),
    SignalDef("fresh_recency_days", "Fresh-permit recency (days)", "derived",
              "number", "date math on issue_date"),
    SignalDef("distress_stalled", "DISTRESS — Stalled", "derived", "bool",
              "issued long ago, no recent status/inspection change"),
    SignalDef("distress_expiring", "DISTRESS — Expiring/Expired", "derived",
              "bool", "expiration date approaching/passed"),
    SignalDef("distress_renewal", "DISTRESS — Extension/Renewal filed",
              "derived", "bool", "renewal permit detected"),
    SignalDef("distress_stopwork", "DISTRESS — Stop-work / Hold", "derived",
              "bool", "status flag"),
    SignalDef("distress_inspections", "DISTRESS — Failed/repeat inspections",
              "derived", "bool", "inspection results"),
    SignalDef("distress_velocity", "DISTRESS — Velocity anomaly", "derived",
              "bool", "slower than peer projects (type/size/region)"),
    SignalDef("new_gc", "New-GC flag", "derived", "bool",
              "contractor NOT in our known contacts"),
    SignalDef("known_gc", "Known-GC / relationship status", "derived", "bool",
              "cross-ref CRM contacts"),
    SignalDef("repeat_gc_count", "Repeat-GC frequency", "derived", "number",
              "# active projects by same GC"),
    SignalDef("geo_shippable", "Geo — shippable / radius", "derived", "bool",
              "geocode + our facility"),
    SignalDef("distance_mi", "Distance from facility (mi)", "derived", "number",
              "haversine from facility"),
    SignalDef("lead_score", "Composite lead score", "derived", "number",
              "weighted blend; default sort", is_facet=False),
    SignalDef("dedup_confidence", "Duplicate-merge confidence", "derived",
              "number", "dedup engine", is_facet=False),
    SignalDef("source_staleness_days", "Source freshness / staleness", "derived",
              "number", "per-jurisdiction last good pull"),

    # ---- C) Enrichment (later phases — defined now so facets pre-exist) ----
    SignalDef("lien_filed", "Mechanic's lien filed", "enrichment", "bool",
              "external liens (phase 4)"),
    SignalDef("litigation", "Construction litigation", "enrichment", "bool",
              "external lawsuits (phase 4)"),
    SignalDef("news_mention", "News mention (award/delay)", "enrichment", "bool",
              "news enrichment (phase 4)"),
    SignalDef("gc_firmographics", "GC firmographics", "enrichment", "category",
              "firmographic enrichment (phase 4)"),
    SignalDef("resolved_contact", "Resolved contact", "enrichment", "bool",
              "contact resolution (phase 4)"),
)

BY_ID: dict[str, SignalDef] = {s.id: s for s in SIGNALS}


def facets() -> list[SignalDef]:
    return [s for s in SIGNALS if s.is_facet]


def by_tier(tier: str) -> list[SignalDef]:
    return [s for s in SIGNALS if s.tier == tier]
