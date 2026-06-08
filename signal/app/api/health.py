from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import get_session

router = APIRouter(tags=["meta"])


@router.get("/health")
def health():
    return {"status": "ok", "service": "sauce.ai/signal"}


@router.get("/health/db")
def health_db(sess: Session = Depends(get_session)):
    try:
        sess.execute(text("SELECT 1"))
        return {"db": "ok"}
    except Exception as exc:  # noqa: BLE001 - boundary
        return {"db": "unavailable", "detail": str(exc)[:200]}
