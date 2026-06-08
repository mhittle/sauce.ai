"""Derived-signal computation (PRD §8B) — the core differentiation.

Pure functions over a project's permits/inspections so they are unit-testable
without a DB. `compute_project_signals` is the orchestrator the ingest
pipeline calls; it returns {signal_id: value} ready to upsert into
project_signals.

The semantic signals here are the cheap rules baseline. PRD §9 layers an
Anthropic LLM pass on top (is_commercial / category / cabinet_relevance /
distress) and caches it on the project; that runs in jobs, not here, and
overrides these when present.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

# --- keyword lexicons (rules baseline; LLM refines later) ------------------
_RESIDENTIAL_HINTS = ("single family", "sfr", "duplex", "townhome", "adu",
                      "dwelling", "residential")
_COMMERCIAL_HINTS = ("commercial", "tenant", "office", "retail", "restaurant",
                     "hotel", "hospitality", "multifamily", "apartment",
                     "warehouse", "industrial", "institutional", "healthcare",
                     "medical", "school", "mixed use")

_CATEGORY_LEXICON = {
    "hospitality": ("hotel", "motel", "resort", "hospitality"),
    "restaurant": ("restaurant", "kitchen", "cafe", "bar ", "food service",
                   "dining"),
    "multifamily": ("multifamily", "apartment", "condo", "townhome",
                    "multi-family", "units"),
    "office": ("office", "tenant improvement", "ti ", "workplace"),
    "retail": ("retail", "store", "shop", "mall", "tenant space"),
    "healthcare": ("hospital", "clinic", "medical", "healthcare", "dental"),
    "education": ("school", "university", "classroom", "education", "campus"),
    "industrial": ("warehouse", "industrial", "manufacturing", "distribution"),
}

_CABINET_TERMS = ("cabinet", "casework", "millwork", "vanity", "vanities",
                  "kitchen", "countertop", "ff&e", "ffe", "fixtures",
                  "built-in", "built in", "cabinetry", "joinery")

_STOPWORK_STATUSES = ("stop work", "stop-work", "stopwork", "on hold",
                      "on-hold", "hold", "suspended")
_EXPIRED_STATUSES = ("expired", "void", "lapsed")
_FINAL_STATUSES = ("final", "finaled", "closed", "complete", "completed",
                   "co issued")
_RENEWAL_HINTS = ("renew", "extension", "extend", "reinstate")

# --- tunable thresholds ----------------------------------------------------
STALLED_DAYS = 180
EXPIRING_WINDOW_DAYS = 30
FRESH_WINDOW_DAYS = 30


@dataclass
class ProjectContext:
    permits: list[dict] = field(default_factory=list)
    inspections: list[dict] = field(default_factory=list)
    today: date = field(default_factory=date.today)
    facility: Optional[tuple[float, float]] = None      # (lat, lng)
    shippable_radius_mi: float = 500.0
    known_contractors: frozenset[str] = frozenset()      # normalized names
    repeat_gc_count: int = 0
    source_last_pull: Optional[date] = None
    peer_median_active_days: Optional[float] = None


def _text(ctx_permits: list[dict]) -> str:
    parts = []
    for p in ctx_permits:
        for k in ("work_description", "permit_type", "permit_subtype",
                  "use_type", "occupancy"):
            v = p.get(k)
            if v:
                parts.append(str(v))
    return " ".join(parts).lower()


def value_tier(valuation: Optional[float]) -> Optional[str]:
    if valuation is None:
        return None
    if valuation >= 5_000_000:
        return "mega"
    if valuation >= 1_000_000:
        return "large"
    if valuation >= 250_000:
        return "mid"
    if valuation >= 50_000:
        return "small"
    return "micro"


def is_commercial(text: str, use_type: Optional[str]) -> bool:
    hay = f"{text} {use_type or ''}".lower()
    if any(h in hay for h in _COMMERCIAL_HINTS):
        return True
    if any(h in hay for h in _RESIDENTIAL_HINTS):
        return False
    return False


def classify_category(text: str) -> Optional[str]:
    best, best_hits = None, 0
    for cat, terms in _CATEGORY_LEXICON.items():
        hits = sum(1 for t in terms if t in text)
        if hits > best_hits:
            best, best_hits = cat, hits
    return best


def cabinet_relevance(text: str) -> float:
    hits = sum(1 for t in _CABINET_TERMS if t in text)
    return min(1.0, round(hits / 3.0, 3))


def casework_intensity(relevance: float) -> str:
    if relevance >= 0.66:
        return "high"
    if relevance >= 0.33:
        return "medium"
    if relevance > 0:
        return "low"
    return "none"


def _max_date(permits: list[dict], key: str) -> Optional[date]:
    vals = [p.get(key) for p in permits if isinstance(p.get(key), date)]
    return max(vals) if vals else None


def stage(permits: list[dict], today: date) -> Optional[str]:
    statuses = " ".join(str(p.get("status") or "").lower() for p in permits)
    if any(s in statuses for s in _FINAL_STATUSES):
        return "near-completion"
    issue = _max_date(permits, "issue_date")
    if issue is None:
        return "just-permitted"
    age = (today - issue).days
    if age <= FRESH_WINDOW_DAYS:
        return "just-permitted"
    return "active"


def fresh_recency_days(permits: list[dict], today: date) -> Optional[int]:
    issue = _max_date(permits, "issue_date")
    return (today - issue).days if issue else None


def distress_stalled(ctx: ProjectContext) -> bool:
    permits = ctx.permits
    statuses = " ".join(str(p.get("status") or "").lower() for p in permits)
    if any(s in statuses for s in _FINAL_STATUSES):
        return False
    issue = _max_date(permits, "issue_date")
    if issue is None or (ctx.today - issue).days < STALLED_DAYS:
        return False
    last_change = _max_date(permits, "last_status_change")
    last_insp = _max_date(ctx.inspections, "inspection_date")
    recent = max([d for d in (last_change, last_insp) if d], default=None)
    if recent is None:
        return True
    return (ctx.today - recent).days >= STALLED_DAYS


def distress_expiring(ctx: ProjectContext) -> bool:
    exp = _max_date(ctx.permits, "expiration_date")
    if exp is None:
        statuses = " ".join(str(p.get("status") or "").lower()
                            for p in ctx.permits)
        return any(s in statuses for s in _EXPIRED_STATUSES)
    return (exp - ctx.today).days <= EXPIRING_WINDOW_DAYS


def distress_renewal(permits: list[dict]) -> bool:
    for p in permits:
        blob = f"{p.get('permit_type') or ''} {p.get('permit_subtype') or ''} " \
               f"{p.get('work_description') or ''}".lower()
        if any(h in blob for h in _RENEWAL_HINTS):
            return True
    return False


def distress_stopwork(permits: list[dict]) -> bool:
    statuses = " ".join(str(p.get("status") or "").lower() for p in permits)
    return any(s in statuses for s in _STOPWORK_STATUSES)


def distress_inspections(inspections: list[dict]) -> bool:
    fails = sum(1 for i in inspections
                if str(i.get("result") or "").lower() in
                ("fail", "failed", "reinspect", "reinspection"))
    return fails >= 2


def distress_velocity(ctx: ProjectContext) -> bool:
    if ctx.peer_median_active_days is None:
        return False
    issue = _max_date(ctx.permits, "issue_date")
    if issue is None:
        return False
    statuses = " ".join(str(p.get("status") or "").lower() for p in ctx.permits)
    if any(s in statuses for s in _FINAL_STATUSES):
        return False
    age = (ctx.today - issue).days
    return age > ctx.peer_median_active_days * 1.5


def haversine_mi(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * \
        math.sin(dlon / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def _project_point(permits: list[dict]) -> Optional[tuple[float, float]]:
    for p in permits:
        lat, lng = p.get("latitude"), p.get("longitude")
        if lat is not None and lng is not None:
            return (float(lat), float(lng))
    return None


def normalize_contractor(name: Optional[str]) -> str:
    if not name:
        return ""
    s = re.sub(r"[^a-z0-9 ]", "", name.lower())
    s = re.sub(r"\b(llc|inc|corp|co|company|ltd|the)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


def compute_project_signals(ctx: ProjectContext) -> dict:
    """Return {signal_id: value} for one project. Values are JSON-friendly."""
    permits = ctx.permits
    text = _text(permits)
    use_type = next((p.get("use_type") for p in permits if p.get("use_type")),
                    None)
    valuation = max((p.get("valuation") or 0) for p in permits) if permits else 0
    relevance = cabinet_relevance(text)

    out: dict = {
        "is_commercial": is_commercial(text, use_type),
        "category": classify_category(text),
        "value_tier": value_tier(valuation or None),
        "cabinet_relevance": relevance,
        "casework_intensity": casework_intensity(relevance),
        "stage": stage(permits, ctx.today),
        "fresh_recency_days": fresh_recency_days(permits, ctx.today),
        "distress_stalled": distress_stalled(ctx),
        "distress_expiring": distress_expiring(ctx),
        "distress_renewal": distress_renewal(permits),
        "distress_stopwork": distress_stopwork(permits),
        "distress_inspections": distress_inspections(ctx.inspections),
        "distress_velocity": distress_velocity(ctx),
        "repeat_gc_count": ctx.repeat_gc_count,
    }

    gc = normalize_contractor(
        next((p.get("contractor_name") for p in permits
              if p.get("contractor_name")), None))
    if gc:
        out["known_gc"] = gc in ctx.known_contractors
        out["new_gc"] = gc not in ctx.known_contractors

    point = _project_point(permits)
    if point and ctx.facility:
        dist = haversine_mi(ctx.facility, point)
        out["distance_mi"] = round(dist, 1)
        out["geo_shippable"] = dist <= ctx.shippable_radius_mi

    if ctx.source_last_pull:
        out["source_staleness_days"] = (ctx.today - ctx.source_last_pull).days

    return {k: v for k, v in out.items() if v is not None}
