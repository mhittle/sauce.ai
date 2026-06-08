"""Coverage / freshness endpoint (PRD §10 coverage dashboard, §16 freshness)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..db import get_session
from ..schemas import JurisdictionOut

router = APIRouter(prefix="/api/jurisdictions", tags=["coverage"])


@router.get("", response_model=list[JurisdictionOut])
def list_jurisdictions(sess: Session = Depends(get_session)):
    try:
        rows = sess.execute(text("""
            SELECT slug, name, state, source_type, active, last_good_pull,
                   known_lag_days,
                   EXTRACT(DAY FROM now() - last_good_pull)::int AS staleness_days
            FROM jurisdictions ORDER BY name
        """)).mappings().all()
    except SQLAlchemyError:
        return []
    return [JurisdictionOut(**{k: r[k] for k in JurisdictionOut.model_fields
                               if k in r}) for r in rows]
