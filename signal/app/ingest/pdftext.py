"""Best-effort text + title extraction for bid-package classification.

Bid attachments aren't always PDFs — many are ZIP archives (often the plan
set), DOCX, or images. We dispatch on the file's magic bytes:
  * %PDF  -> pypdf (page/size capped)
  * PK..  -> ZIP: pull text from PDF members (the zipped plan/spec set)
  * else  -> "" (no OCR yet)
Any failure degrades to ("", "") / "". pypdf's noisy warnings ("invalid pdf
header", "EOF marker not found") are silenced.
"""
from __future__ import annotations

import io
import logging
import re
import warnings
import zipfile
from typing import Optional

logging.getLogger("pypdf").setLevel(logging.ERROR)

MAX_PAGES = 40
MAX_BYTES = 60 * 1024 * 1024     # skip files larger than this
ZIP_MAX_PDFS = 8                 # parse at most N PDFs out of an archive


def _clean_title(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = re.sub(r"\s+", " ", s).strip()
    if not (6 <= len(s) <= 120):
        return None
    if sum(c.isalpha() for c in s) < 4:
        return None
    if s.lower() in {"download", "document", "view", "file", "untitled"}:
        return None
    return s


def _first_heading(text: str) -> Optional[str]:
    for line in text.splitlines()[:40]:
        cleaned = _clean_title(line)
        if cleaned and len(cleaned.split()) >= 2:
            return cleaned
    return None


def _pdf_meta(content: bytes, max_pages: int) -> tuple[Optional[str], str]:
    from pypdf import PdfReader
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        reader = PdfReader(io.BytesIO(content))
        text = "\n".join((p.extract_text() or "")
                         for p in reader.pages[:max_pages])
        meta_title = None
        try:
            meta_title = reader.metadata.title if reader.metadata else None
        except Exception:        # noqa: BLE001
            meta_title = None
    title = _clean_title(meta_title) or _first_heading(text)
    return title, text


def _zip_meta(content: bytes, max_pages: int) -> tuple[Optional[str], str]:
    title = None
    parts: list[str] = []
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        pdfs = [n for n in zf.namelist() if n.lower().endswith(".pdf")][:ZIP_MAX_PDFS]
        for name in pdfs:
            try:
                data = zf.read(name)
                if 0 < len(data) <= MAX_BYTES and data[:4] == b"%PDF":
                    t, txt = _pdf_meta(data, max_pages)
                    title = title or t
                    if txt:
                        parts.append(txt)
            except Exception:        # noqa: BLE001 - skip a bad member
                continue
    return title, "\n".join(parts)


def extract_pdf_meta(content: bytes, max_pages: int = MAX_PAGES
                     ) -> tuple[Optional[str], str]:
    """Return (title, text). Best-effort; degrades to (None, "")."""
    if not content or len(content) > MAX_BYTES:
        return None, ""
    try:
        if content[:4] == b"%PDF":
            return _pdf_meta(content, max_pages)
        if content[:2] == b"PK":
            return _zip_meta(content, max_pages)
    except Exception:                # noqa: BLE001 - any parse failure
        return None, ""
    return None, ""


def extract_pdf_text(content: bytes, max_pages: int = MAX_PAGES) -> str:
    return extract_pdf_meta(content, max_pages)[1]
