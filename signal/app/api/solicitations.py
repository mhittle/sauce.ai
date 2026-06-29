"""Solicitations API (PRD PlanHub track) — public bids + attached plans.

Filterable list, default sort by soonest bid due date. Degrades to empty if
the table isn't present yet (migrate-after-deploy tolerance), never a 500.
"""
from __future__ import annotations

import requests
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..db import get_session
from ..integrations import scribe
from ..schemas import (SolicitationDetailOut, SolicitationDocOut,
                       SolicitationListOut, SolicitationOut, SourceCountOut)
from .documents import _with_api_key

router = APIRouter(prefix="/api/solicitations", tags=["solicitations"])

_SORT_COLUMNS = {
    "due_date": "s.due_date",
    "posted_date": "s.posted_date",
    "estimated_value": "s.estimated_value",
    "cabinet_score": "s.cabinet_score",
}


@router.get("", response_model=SolicitationListOut)
def list_solicitations(
    sess: Session = Depends(get_session),
    source_type: str | None = None,
    state: str | None = None,
    q: str | None = None,
    has_docs: bool = False,
    cabinet: bool = False,
    sort: str = "cabinet_score",
    dir: str = "desc",
    limit: int = Query(50, le=500),
    offset: int = 0,
):
    order_col = _SORT_COLUMNS.get(sort, "s.cabinet_score")
    direction = "ASC" if dir.lower() == "asc" else "DESC"
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
    if cabinet:
        where.append("s.cabinet_flag = TRUE")
    clause = " AND ".join(where)

    try:
        total = sess.execute(text(
            f"SELECT count(*) FROM solicitations s WHERE {clause}"), params).scalar()
        rows = sess.execute(text(f"""
            SELECT s.id, s.source_type, s.title, s.agency, s.naics, s.state,
                   s.place_city, s.estimated_value, s.posted_date, s.due_date,
                   s.status, s.source_url, s.cabinet_flag, s.cabinet_score,
                   (SELECT count(*) FROM solicitation_documents d
                    WHERE d.solicitation_id = s.id) AS doc_count
            FROM solicitations s
            WHERE {clause}
            ORDER BY {order_col} {direction} NULLS LAST, s.due_date ASC NULLS LAST, s.id DESC
            LIMIT :limit OFFSET :offset
        """), params).mappings().all()
    except SQLAlchemyError:
        return SolicitationListOut(total=0, items=[])

    return SolicitationListOut(
        total=total or 0,
        items=[SolicitationOut(**{k: r[k] for k in SolicitationOut.model_fields
                                  if k in r}) for r in rows])


# NOTE: declared before /{solicitation_id} so "sources" isn't parsed as an int.
@router.get("/sources", response_model=list[SourceCountOut])
def list_sources(sess: Session = Depends(get_session)):
    """Distinct source_types present (with counts) — drives the source filter."""
    try:
        rows = sess.execute(text("""
            SELECT source_type, count(*) AS count FROM solicitations
            GROUP BY source_type ORDER BY count DESC, source_type
        """)).mappings().all()
    except SQLAlchemyError:
        return []
    return [SourceCountOut(source_type=r["source_type"], count=r["count"])
            for r in rows]


@router.get("/{solicitation_id}", response_model=SolicitationDetailOut)
def get_solicitation(solicitation_id: int, sess: Session = Depends(get_session)):
    try:
        row = sess.execute(text("""
            SELECT s.id, s.source_type, s.title, s.agency, s.description, s.naics,
                   s.state, s.place_city, s.estimated_value, s.posted_date,
                   s.due_date, s.status, s.source_url
            FROM solicitations s WHERE s.id = :id
        """), {"id": solicitation_id}).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="solicitation not found")
        docs = sess.execute(text("""
            SELECT id, name, url, doc_type FROM solicitation_documents
            WHERE solicitation_id = :id ORDER BY id
        """), {"id": solicitation_id}).mappings().all()
    except HTTPException:
        raise
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="database not ready")

    return SolicitationDetailOut(
        **{k: row[k] for k in SolicitationOut.model_fields if k in row},
        description=row["description"],
        doc_count=len(docs),
        documents=[SolicitationDocOut(**dict(d)) for d in docs])


@router.post("/{solicitation_id}/documents/{doc_id}/send-to-scribe")
def send_document_to_scribe(
    solicitation_id: int, doc_id: int, sess: Session = Depends(get_session)):
    """Hand a bid PDF to scribe to start a quote takeoff.

    Fetches the document server-side (so the source api-key stays here), checks
    it's actually a PDF, and POSTs the bytes to scribe. Returns the new takeoff
    id + a deep link to review it in scribe.
    """
    if not scribe.is_configured():
        raise HTTPException(status_code=503,
                            detail="scribe connector not configured")
    try:
        row = sess.execute(text(
            "SELECT url, name FROM solicitation_documents "
            "WHERE id = :doc AND solicitation_id = :sol"),
            {"doc": doc_id, "sol": solicitation_id}).mappings().first()
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="database not ready")
    if not row:
        raise HTTPException(status_code=404, detail="document not found")

    url = row["url"]
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="unsupported document url")

    try:
        upstream = requests.get(_with_api_key(url), timeout=60)
        upstream.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502,
                            detail=f"upstream fetch failed: {str(exc)[:200]}")

    data = upstream.content
    if data[:4] != b"%PDF":
        raise HTTPException(
            status_code=400,
            detail="document is not a PDF (scribe takeoffs need a PDF plan/spec)")

    filename = (row["name"] or f"solicitation-{solicitation_id}-doc-{doc_id}")
    try:
        return scribe.send_pdf_to_scribe(filename, data)
    except scribe.ScribeNotConfigured:
        raise HTTPException(status_code=503,
                            detail="scribe connector not configured")
    except scribe.ScribeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
