"""Projects API (PRD §10) — filterable list (default sort lead_score) + detail.

All DB reads degrade to a graceful empty result if the schema isn't present
yet (migrate-after-deploy tolerance), never a 500.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..db import get_session
from ..schemas import (PermitOut, ProjectDetailOut, ProjectListOut, ProjectOut)
from ..signals.scoring import default_rule, why_flagged

router = APIRouter(prefix="/api/projects", tags=["projects"])

# friendly sort key -> SQL expression (whitelist; avoids injection)
_SORT_COLUMNS = {
    "lead_score": "p.lead_score",
    "updated_at": "p.updated_at",
    "value_tier": "p.value_tier",
    "category": "p.category",
    "status": "p.status",
    "jurisdiction": "j.name",
    "primary_address": "p.primary_address",
}


@router.get("", response_model=ProjectListOut)
def list_projects(
    sess: Session = Depends(get_session),
    status: str | None = None,
    category: str | None = None,
    value_tier: str | None = None,
    min_score: float | None = None,
    q: str | None = None,
    signal: list[str] = Query(default=[]),     # e.g. ?signal=distress_stalled
    sort: str = "lead_score",
    dir: str = "desc",
    limit: int = Query(50, le=500),
    offset: int = 0,
):
    order_col = _SORT_COLUMNS.get(sort, "p.lead_score")
    direction = "ASC" if dir.lower() == "asc" else "DESC"
    where = ["1=1"]
    params: dict = {"limit": limit, "offset": offset}
    if status:
        where.append("p.status = :status"); params["status"] = status
    if category:
        where.append("p.category = :category"); params["category"] = category
    if value_tier:
        where.append("p.value_tier = :vt"); params["vt"] = value_tier
    if min_score is not None:
        where.append("p.lead_score >= :ms"); params["ms"] = min_score
    if q:
        where.append("p.primary_address ILIKE :q"); params["q"] = f"%{q}%"
    for i, sig in enumerate(signal):
        where.append(f"""EXISTS (SELECT 1 FROM project_signals ps
            WHERE ps.project_id = p.id AND ps.signal_id = :sig{i}
            AND COALESCE(ps.value_bool, ps.value_num <> 0, TRUE))""")
        params[f"sig{i}"] = sig
    clause = " AND ".join(where)

    try:
        total = sess.execute(text(
            f"SELECT count(*) FROM projects p WHERE {clause}"), params).scalar()
        rows = sess.execute(text(f"""
            SELECT p.id, p.primary_address, j.name AS jurisdiction, p.category,
                   p.value_tier, p.lead_score, p.status, p.crm_id, p.updated_at,
                   ST_Y(p.geom) AS latitude, ST_X(p.geom) AS longitude
            FROM projects p LEFT JOIN jurisdictions j ON j.id = p.jurisdiction_id
            WHERE {clause}
            ORDER BY {order_col} {direction} NULLS LAST, p.id DESC
            LIMIT :limit OFFSET :offset
        """), params).mappings().all()
    except SQLAlchemyError:
        return ProjectListOut(total=0, items=[])

    return ProjectListOut(
        total=total or 0,
        items=[ProjectOut(**{k: r[k] for k in ProjectOut.model_fields if k in r})
               for r in rows])


@router.get("/{project_id}", response_model=ProjectDetailOut)
def get_project(project_id: int, sess: Session = Depends(get_session)):
    try:
        row = sess.execute(text("""
            SELECT p.id, p.primary_address, j.name AS jurisdiction, p.category,
                   p.value_tier, p.lead_score, p.status, p.crm_id, p.updated_at,
                   ST_Y(p.geom) AS latitude, ST_X(p.geom) AS longitude
            FROM projects p LEFT JOIN jurisdictions j ON j.id = p.jurisdiction_id
            WHERE p.id = :id
        """), {"id": project_id}).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="project not found")

        permits = sess.execute(text("""
            SELECT permit_id, permit_type, work_description, valuation, status,
                   issue_date, expiration_date, contractor_name, source_url
            FROM permits WHERE project_id = :id ORDER BY issue_date DESC NULLS LAST
        """), {"id": project_id}).mappings().all()

        sig_rows = sess.execute(text("""
            SELECT signal_id, value_bool, value_num, value_text, value_json
            FROM project_signals WHERE project_id = :id
        """), {"id": project_id}).mappings().all()
    except HTTPException:
        raise
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="database not ready")

    signals: dict = {}
    for s in sig_rows:
        for col in ("value_bool", "value_num", "value_text", "value_json"):
            if s[col] is not None:
                signals[s["signal_id"]] = s[col]
                break

    detail = ProjectDetailOut(
        **{k: row[k] for k in ProjectOut.model_fields if k in row},
        permits=[PermitOut(**{k: p[k] for k in PermitOut.model_fields if k in p})
                 for p in permits],
        signals=signals,
        why_flagged=why_flagged(signals, default_rule()["weights"]),
    )
    return detail
