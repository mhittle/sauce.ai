"""Inline document proxy — view solicitation plan/spec PDFs without downloading.

Streams a stored `solicitation_documents.url` back through our API with
`Content-Disposition: inline` so the browser's PDF viewer renders it in an
iframe, and so the SAM.gov api_key (needed for api.sam.gov file links) stays
server-side. Bounded to URLs already in our DB (no open SSRF proxy).

This is the lightweight, on-demand path; the roadmap "document store + PDF
parse" item will later cache bytes to object storage.
"""
from __future__ import annotations

import requests
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_session

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _with_api_key(url: str) -> str:
    s = get_settings()
    if "api.sam.gov" in url and s.samgov_api_key and "api_key=" not in url:
        return url + ("&" if "?" in url else "?") + f"api_key={s.samgov_api_key}"
    return url


@router.get("/{doc_id}")
def view_document(doc_id: int, sess: Session = Depends(get_session)):
    try:
        row = sess.execute(text(
            "SELECT url, name FROM solicitation_documents WHERE id = :id"),
            {"id": doc_id}).mappings().first()
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="database not ready")
    if not row:
        raise HTTPException(status_code=404, detail="document not found")

    url = row["url"]
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="unsupported document url")

    try:
        upstream = requests.get(_with_api_key(url), stream=True, timeout=30)
        upstream.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502,
                            detail=f"upstream fetch failed: {str(exc)[:200]}")

    content_type = upstream.headers.get("Content-Type", "application/pdf")
    filename = (row["name"] or "document").replace('"', "")

    def stream():
        try:
            for chunk in upstream.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    return StreamingResponse(
        stream(), media_type=content_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"'})
