"""Best-effort PDF text extraction for bid-package classification.

Caps pages/size so a giant image-heavy plan set can't hang the job. pypdf is
imported lazily so the rest of the package imports without it. Any failure
(non-PDF, encrypted, corrupt, image-only) degrades to "".
"""
from __future__ import annotations

import io

MAX_PAGES = 40
MAX_BYTES = 60 * 1024 * 1024     # skip parsing PDFs larger than this


def extract_pdf_text(content: bytes, max_pages: int = MAX_PAGES) -> str:
    if not content or len(content) > MAX_BYTES:
        return ""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content))
        pages = reader.pages[:max_pages]
        return "\n".join((p.extract_text() or "") for p in pages)
    except Exception:        # noqa: BLE001 - any parse failure -> no text
        return ""
