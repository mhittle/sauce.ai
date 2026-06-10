"""Classify solicitations for casework/cabinetry from their bid packages.

For each solicitation: combine title + description + extracted text of its
attached PDFs, run the casework classifier, and store `cabinet_flag` /
`cabinet_score` (+ per-doc `text_extract` and a best-effort document `title`).
Cabinetry jobs then float to the top of the Solicitations view. DB-backed; the
classifier + PDF util are tested separately.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

import requests
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import get_settings
from ..signals.casework import classify_casework
from .pdftext import MAX_BYTES, extract_pdf_meta

_UA = {"User-Agent": "Mozilla/5.0 sauce.ai-signal"}
_TEXT_STORE_CHARS = 40_000
_GENERIC_NAMES = {"download", "document", "view", "file", ""}


def _with_api_key(url: str) -> str:
    s = get_settings()
    if "api.sam.gov" in url and s.samgov_api_key and "api_key=" not in url:
        return url + ("&" if "?" in url else "?") + f"api_key={s.samgov_api_key}"
    return url


def _cd_filename(resp: requests.Response) -> Optional[str]:
    cd = resp.headers.get("Content-Disposition", "")
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd, re.I)
    if not m:
        return None
    from urllib.parse import unquote
    name = unquote(m.group(1)).strip()
    return re.sub(r"\.(pdf|zip|docx?|xlsx?)$", "", name, flags=re.I) or None


def _download(url: str) -> tuple[bytes | None, Optional[str]]:
    """Return (content, content-disposition filename)."""
    try:
        resp = requests.get(_with_api_key(url), stream=True, timeout=60,
                            headers=_UA)
        resp.raise_for_status()
        fname = _cd_filename(resp)
        buf = bytearray()
        for chunk in resp.iter_content(chunk_size=65536):
            buf.extend(chunk)
            if len(buf) > MAX_BYTES:
                resp.close()
                return None, fname
        return bytes(buf), fname
    except requests.RequestException:
        return None, None


def _meaningful(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    n = re.sub(r"\s+", " ", name).strip()
    if n.lower() in _GENERIC_NAMES or n.isdigit() or len(n) < 4:
        return None
    return n


def _pick_title(link_name, cd_name, pdf_title, url) -> Optional[str]:
    for cand in (link_name, cd_name, pdf_title):
        good = _meaningful(cand)
        if good:
            return good[:200]
    base = url.rstrip("/").split("/")[-1]
    base = re.sub(r"\.(pdf|zip|docx?|xlsx?)$", "", base, flags=re.I)
    return _meaningful(base)


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
            "SELECT id, url, name FROM solicitation_documents WHERE solicitation_id = :id"),
            {"id": r["id"]}).mappings().all()
        for d in docs:
            content, cd_name = _download(d["url"])
            pdf_title, txt = extract_pdf_meta(content) if content else (None, "")
            if txt:
                combined += "\n" + txt
            title = _pick_title(d["name"], cd_name, pdf_title, d["url"])
            sess.execute(text("""
                UPDATE solicitation_documents
                SET text_extract = COALESCE(:t, text_extract),
                    name = COALESCE(:title, name)
                WHERE id = :id
            """), {"t": txt[:_TEXT_STORE_CHARS] or None, "title": title,
                   "id": d["id"]})

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
