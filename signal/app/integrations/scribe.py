"""Scribe connector — hand a bid PDF to sauce.ai/scribe to be quoted.

Signal finds and ranks RFPs; scribe reads plan sets and builds the quote. This
module is the server-side bridge: it POSTs the PDF bytes to scribe's multipart
`/takeoffs` endpoint using a shared service token (so the SAM.gov api_key and
the scribe credential both stay server-side, never in the browser).

Auto-*submission* of a bid is deliberately out of scope — this only kicks off a
quote draft for a human to review in scribe.
"""
from __future__ import annotations

import requests

from ..config import get_settings


class ScribeNotConfigured(RuntimeError):
    """SCRIBE_API_URL / SCRIBE_SERVICE_TOKEN aren't set — connector disabled."""


class ScribeError(RuntimeError):
    """Scribe rejected the handoff or was unreachable."""


def is_configured() -> bool:
    s = get_settings()
    return bool(s.scribe_api_url and s.scribe_service_token)


def send_pdf_to_scribe(filename: str, data: bytes) -> dict:
    """Create a scribe takeoff from a PDF. Returns takeoff id/status + a deep
    link to the review screen (when SCRIBE_WEB_URL is set).
    """
    s = get_settings()
    if not s.scribe_api_url or not s.scribe_service_token:
        raise ScribeNotConfigured(
            "scribe connector not configured (set SCRIBE_API_URL and "
            "SCRIBE_SERVICE_TOKEN)")

    # Scribe keys the source kind off the filename extension, so force .pdf.
    if not filename.lower().endswith(".pdf"):
        filename = f"{filename}.pdf"

    url = s.scribe_api_url.rstrip("/") + "/takeoffs"
    try:
        resp = requests.post(
            url,
            files={"file": (filename, data, "application/pdf")},
            headers={"Authorization": f"Bearer {s.scribe_service_token}"},
            timeout=120,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise ScribeError(f"scribe handoff failed: {str(exc)[:200]}") from exc

    takeoff = resp.json()
    takeoff_id = takeoff.get("id")
    review_url = None
    if s.scribe_web_url and takeoff_id:
        review_url = f"{s.scribe_web_url.rstrip('/')}/takeoffs/{takeoff_id}"
    return {
        "takeoff_id": takeoff_id,
        "status": takeoff.get("status"),
        "review_url": review_url,
    }
