"""Best-effort text extraction for bid-package classification.

Bid attachments aren't always PDFs — many are ZIP archives (often the plan
set), DOCX, or images. We dispatch on the file's magic bytes:
  * %PDF  -> pypdf (page/size capped)
  * PK..  -> ZIP: pull text from PDF members (the zipped plan/spec set)
  * else  -> "" (no OCR yet)
Any failure degrades to "". pypdf's noisy warnings ("invalid pdf header",
"EOF marker not found") are silenced — they fired once per non-PDF attachment.
"""
from __future__ import annotations

import io
import logging
import warnings
import zipfile

logging.getLogger("pypdf").setLevel(logging.ERROR)

MAX_PAGES = 40
MAX_BYTES = 60 * 1024 * 1024     # skip files larger than this
ZIP_MAX_PDFS = 8                 # parse at most N PDFs out of an archive


def _pdf_text(content: bytes, max_pages: int) -> str:
    from pypdf import PdfReader
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        reader = PdfReader(io.BytesIO(content))
        return "\n".join((p.extract_text() or "") for p in reader.pages[:max_pages])


def _zip_pdf_text(content: bytes, max_pages: int) -> str:
    out: list[str] = []
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        pdfs = [n for n in zf.namelist() if n.lower().endswith(".pdf")][:ZIP_MAX_PDFS]
        for name in pdfs:
            try:
                data = zf.read(name)
                if 0 < len(data) <= MAX_BYTES and data[:4] == b"%PDF":
                    out.append(_pdf_text(data, max_pages))
            except Exception:        # noqa: BLE001 - skip a bad member
                continue
    return "\n".join(t for t in out if t)


def extract_pdf_text(content: bytes, max_pages: int = MAX_PAGES) -> str:
    if not content or len(content) > MAX_BYTES:
        return ""
    try:
        if content[:4] == b"%PDF":
            return _pdf_text(content, max_pages)
        if content[:2] == b"PK":     # zip / docx / xlsx — recover PDF members
            return _zip_pdf_text(content, max_pages)
    except Exception:                # noqa: BLE001 - any parse failure -> no text
        return ""
    return ""
