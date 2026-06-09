"""Classify solicitations for casework/cabinetry from their bid packages.

For each solicitation: combine title + description + extracted text of its
attached PDFs, run the casework classifier, and store `cabinet_flag` /
`cabinet_score` (+ per-doc `text_extract`). Cabinetry jobs then float to the
top of the Solicitations view. DB-backed; the classifier + PDF util are tested
separately.
"""
from __future__ import annotations

from datetime import datetime, timezone

import requests
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import get_settings
from ..signals.casework import classify_casework
from .pdftext import MAX_BYTES, extract_pdf_text

_UA = {"User-Agent": "Mozilla/5.0 sauce.ai-signal"}
_TEXT_STORE_CHARS = 40_000


def _with_api_key(url: str) -> str:
    s = get_settings()
    if "api.sam.gov" in url and s.samgov_api_key and "api_key=" not in url:
        return url + ("&" if "?" in url else "?") + f"api_key={s.samgov_api_key}"
    return url


def _download(url: str) -> bytes | None:
    try:
        resp = requests.get(_with_api_key(url), stream=True, timeout=45,
                            headers=_UA)
        resp.raise_for_status()
        buf = bytearray()
        for chunk in resp.iter_content(chunk_size=65536):
            buf.extend(chunk)
            if len(buf) > MAX_BYTES:
                resp.close()
                return None
        return bytes(buf)
    except requests.RequestException:
        return None


def classify_solicitations(sess: Session, slug: str | None = None,
                           limit: int | None = None,
                           reclassify: bool = False) -> dict:
    where = ["1=1"]
    params: dict = {}
    if not reclassify:
        where.append("classified_at IS NULL")
    if slug:
        where.append("source_type = :slug"); params["slug"] = slug
    clause = " AND ".join(where)
    lim = f"LIMIT {int(limit)}" if limit else ""

    rows = sess.execute(text(f"""
        SELECT id, title, description, source_type FROM solicitations
        WHERE {clause} ORDER BY id {lim}
    """), params).mappings().all()

    classified = flagged = 0
    for r in rows:
        combined = " ".join(filter(None, [r["title"], r["description"]]))
        docs = sess.execute(text(
            "SELECT id, url FROM solicitation_documents WHERE solicitation_id = :id"),
            {"id": r["id"]}).mappings().all()
        for d in docs:
            content = _download(d["url"])
            txt = extract_pdf_text(content) if content else ""
            if txt:
                combined += "\n" + txt
                sess.execute(text(
                    "UPDATE solicitation_documents SET text_extract = :t WHERE id = :id"),
                    {"t": txt[:_TEXT_STORE_CHARS], "id": d["id"]})

        result = classify_casework(combined)
        sess.execute(text("""
            UPDATE solicitations SET cabinet_flag = :flag, cabinet_score = :score,
                classified_at = now() WHERE id = :id
        """), {"flag": result["flag"], "score": result["score"], "id": r["id"]})
        classified += 1
        flagged += 1 if result["flag"] else 0
        if classified % 20 == 0:
            sess.commit()
    sess.commit()
    return {"classified": classified, "flagged": flagged,
            "at": datetime.now(timezone.utc).isoformat()}
