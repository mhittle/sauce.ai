"""Solicitations API (PRD PlanHub track) — public bids + attached plans.

Filterable list, default sort by soonest bid due date. Degrades to empty if
the table isn't present yet (migrate-after-deploy tolerance), never a 500.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..db import get_session
from ..schemas import SolicitationListOut, SolicitationOut

router = APIRouter(prefix="/api/solicitations", tags=["solicitations"])

_SORT_COLUMNS = {
    "due_date": "s.due_date",
    "posted_date": "s.posted_date",
    "estimated_value": "s.estimated_value",
}


@router.get("", response_model=SolicitationListOut)
def list_solicitations(
    sess: Session = Depends(get_session),
    source_type: str | None = None,
    state: str | None = None,
    q: str | None = None,
    has_docs: bool = False,
    sort: str = "due_date",
    dir: str = "asc",
    limit: int = Query(50, le=500),
    offset: int = 0,
):
    order_col = _SORT_COLUMNS.get(sort, "s.due_date")
    direction = "DESC" if dir.lower() == "desc" else "ASC"
    where = ["1=1"]
    params: dict = {"limit": limit, "offset": offset}
    if source_type:
        where.append("s.source_type = :st"); params["st"] = source_type
    if state:
        where.append("s.state = :state"); params["state"] = state
    if q:
        where.append("s.title ILIKE :q"); params["q"] = f"%{q}%"
    if has_docs:
        where.append("""EXISTS (SELECT 1 FROM solicitation_documents d
            WHERE d.solicitation_id = s.id)""")
    clause = " AND ".join(where)

    try:
        total = sess.execute(text(
            f"SELECT count(*) FROM solicitations s WHERE {clause}"), params).scalar()
        rows = sess.execute(text(f"""
            SELECT s.id, s.source_type, s.title, s.agency, s.naics, s.state,
                   s.place_city, s.estimated_value, s.posted_date, s.due_date,
                   s.status, s.source_url,
                   (SELECT count(*) FROM solicitation_documents d
                    WHERE d.solicitation_id = s.id) AS doc_count
            FROM solicitations s
            WHERE {clause}
            ORDER BY {order_col} {direction} NULLS LAST, s.id DESC
            LIMIT :limit OFFSET :offset
        """), params).mappings().all()
    except SQLAlchemyError:
        return SolicitationListOut(total=0, items=[])

    return SolicitationListOut(
        total=total or 0,
        items=[SolicitationOut(**{k: r[k] for k in SolicitationOut.model_fields
                                  if k in r}) for r in rows])
