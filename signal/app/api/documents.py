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


def sniff_content_type(first: bytes, upstream_ct: str | None) -> tuple[str, str]:
    """Decide (Content-Type, disposition) from the file's magic bytes.

    Sources like CivicPlus DocumentCenter serve PDFs as
    application/octet-stream, which browsers DOWNLOAD instead of rendering
    (in an iframe or a new tab). Forcing application/pdf for real PDFs fixes
    both. ZIP plan sets can't render inline, so they're an attachment.
    """
    if first[:4] == b"%PDF":
        return "application/pdf", "inline"
    if first[:2] == b"PK":
        return "application/zip", "attachment"
    return (upstream_ct or "application/octet-stream"), "inline"


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
        upstream = requests.get(_with_api_key(url), stream=True, timeout=60)
        upstream.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502,
                            detail=f"upstream fetch failed: {str(exc)[:200]}")

    # Peek the first bytes to set a real Content-Type (see sniff_content_type).
    chunks = upstream.iter_content(chunk_size=65536)
    first = next(chunks, b"")
    content_type, disposition = sniff_content_type(
        first, upstream.headers.get("Content-Type"))
    filename = (row["name"] or "document").replace('"', "")

    def stream():
        try:
            if first:
                yield first
            for chunk in chunks:
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    return StreamingResponse(
        stream(), media_type=content_type,
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'})
