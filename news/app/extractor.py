"""Article body extraction.

`extract_body(url, *, session, timeout)` fetches the article URL and uses
trafilatura to pull out main body text + author + lead image. Returns a
dict suitable for the `article_bodies` row, or None if nothing extractable.

Run from `jobs/classify_pending.py` alongside paywall detection. Wallclock-
bounded by the caller — this module does not retry on its own.

trafilatura is imported lazily so unit tests can stub the import and the
Flask request path (which never extracts) doesn't pay the lxml cost.
"""
import re

import requests

UA = "Mozilla/5.0 (compatible; sauce.ai-news/1.0; +https://sauce.ai)"

MAX_BODY_BYTES = 1024 * 1024  # 1 MB cap — body pages bigger than this are almost always junk.
MIN_WORDS = 60  # below this we consider extraction "empty" (RSS-only stub, paywall snippet, etc.)

_WS = re.compile(r"\s+")


class ExtractResult(dict):
    """Dict with explicit keys to keep callers honest.

    Keys: body_text, body_html, lead_image, author, word_count, status.
    status is one of: 'ok', 'empty', 'blocked', 'error'.
    """


def _empty(status):
    return ExtractResult(
        body_text=None, body_html=None, lead_image=None, author=None,
        word_count=0, status=status,
    )


def _fetch(url, session, timeout):
    sess = session or requests
    try:
        resp = sess.get(
            url,
            timeout=(min(5.0, timeout), timeout),
            headers={"User-Agent": UA, "Accept": "text/html,*/*;q=0.5"},
            allow_redirects=True,
            stream=True,
        )
    except requests.RequestException:
        return None, "error"
    try:
        try:
            raw = resp.raw.read(MAX_BODY_BYTES, decode_content=True) or b""
        except Exception:
            return None, "error"
        status = resp.status_code
    finally:
        resp.close()
    if status in (401, 402, 403, 451) or status >= 400:
        return None, "blocked"
    text = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else str(raw)
    return text, "ok"


def _extract_with_trafilatura(html, url):
    """Run trafilatura. Returns (text, body_html, meta_dict) or (None, None, {})."""
    import trafilatura  # lazy: heavy lxml dep

    text = trafilatura.extract(
        html, url=url, include_comments=False, include_tables=False,
        favor_recall=True, with_metadata=False,
    )
    body_html = trafilatura.extract(
        html, url=url, include_comments=False, include_tables=False,
        favor_recall=True, with_metadata=False, output_format="html",
    )
    meta = trafilatura.extract_metadata(html) if hasattr(trafilatura, "extract_metadata") else None
    meta_dict = {}
    if meta is not None:
        author = getattr(meta, "author", None)
        image = getattr(meta, "image", None)
        if author:
            meta_dict["author"] = author
        if image:
            meta_dict["lead_image"] = image
    return text, body_html, meta_dict


def extract_body(url, *, session=None, timeout=8.0):
    """Fetch + extract. Returns an ExtractResult dict (never None).

    Caller writes this to article_bodies regardless of status, so empty/
    blocked/error rows are recorded and we don't retry forever.
    """
    if not url:
        return _empty("error")

    html, fetch_status = _fetch(url, session, timeout)
    if fetch_status != "ok" or not html:
        return _empty(fetch_status)

    try:
        text, body_html, meta = _extract_with_trafilatura(html, url)
    except Exception:
        return _empty("error")

    if not text:
        return _empty("empty")

    text = _WS.sub(" ", text).strip()
    word_count = len(text.split())
    if word_count < MIN_WORDS:
        return _empty("empty")

    return ExtractResult(
        body_text=text,
        body_html=body_html,
        lead_image=(meta.get("lead_image") or None),
        author=(meta.get("author") or None),
        word_count=word_count,
        status="ok",
    )
