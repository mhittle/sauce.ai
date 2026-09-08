"""Claim — health-headline reality check (anonymous, rate-limited).

GET  /claim            the form
POST /claim            HTMX: a URL or a pasted headline + paragraph
GET  /claim/<id>       permalink to a saved card

Same request-path class as `/ask`: a single-flight, user-initiated
synchronous model pipeline (two Haiku calls + one Sonnet call), never a
500 on model failure. Results are cached in `claim_checks` by URL hash so
a shared link is checked once. A missing table (migration not yet
applied) degrades to an un-persisted card — NOT BUG-007 class.
"""
import ipaddress
import json
from datetime import datetime, timezone
from urllib.parse import urlsplit

import pymysql
from flask import (
    Blueprint, abort, current_app, render_template, request, url_for,
)

from .. import claim as claim_mod
from ..claim_pipeline import run_check
from ..classifier import LLMUnavailable
from ..db import execute, get_conn, query
from ..extractor import extract_body
from ..ratelimit import SlidingWindowLimiter, client_ip

bp = Blueprint("claim", __name__)

DISCLAIMER = ("Claim grades how a headline reports a study. It is not medical "
              "advice and says nothing about whether a treatment is right for you.")

MAX_URL_CHARS = 2000
MIN_TEXT_CHARS = 40
MAX_TEXT_CHARS = 20000


def _config_int(key, default):
    try:
        return int(current_app.config.get(key, default))
    except (TypeError, ValueError):
        return default


def _utc_midnight():
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _ip_limiter():
    ext = current_app.extensions
    lim = ext.get("claim_ip_limiter")
    if lim is None:
        lim = SlidingWindowLimiter(_config_int("CLAIM_RATE_PER_IP_HOUR", 10), 3600)
        ext["claim_ip_limiter"] = lim
    return lim


def _daily_fallback_limiter():
    ext = current_app.extensions
    lim = ext.get("claim_day_limiter")
    if lim is None:
        lim = SlidingWindowLimiter(_config_int("CLAIM_DAILY_CAP", 200), 86400)
        ext["claim_day_limiter"] = lim
    return lim


def _today_count():
    """New checks so far today (UTC), or None when the table is absent."""
    try:
        row = query("SELECT COUNT(*) AS n FROM claim_checks WHERE created_at >= %s",
                    (_utc_midnight(),), one=True)
    except pymysql.err.ProgrammingError:
        return None
    return int(row["n"]) if row else 0


def _daily_cap_ok():
    cap = _config_int("CLAIM_DAILY_CAP", 200)
    count = _today_count()
    if count is None:
        return _daily_fallback_limiter().hit("global")
    return count < cap


def _record_llm_usage(usages):
    for usage in usages or []:
        try:
            execute(
                "INSERT INTO llm_usage (model, input_tokens, output_tokens, "
                "cache_read_tokens, articles, est_cost_usd) VALUES (%s, %s, %s, %s, %s, %s)",
                (usage.get("model"), int(usage.get("input_tokens", 0)),
                 int(usage.get("output_tokens", 0)), int(usage.get("cache_read_tokens", 0)),
                 1, float(usage.get("est_cost_usd", 0.0))),
            )
        except Exception:
            pass


def _save(result, *, input_kind, url=None):
    """Persist one check. Returns the new id, or None when `claim_checks`
    is missing (pre-migration) — the card still renders, just without a
    permalink."""
    study = dict(result.get("study") or {})
    try:
        check_id = execute(
            "INSERT INTO claim_checks (article_id, url_hash, input_kind, headline, "
            "source_url, claim_json, study_json, numbers_json, flags_json, grade, status) "
            "VALUES (NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                claim_mod.url_hash(url) if url else None,
                input_kind,
                (result.get("headline") or "")[:500],
                (url or None) and url[:2000],
                json.dumps(result.get("claim") or {}),
                json.dumps({"study": study or None, "fields": result.get("fields") or {}}),
                json.dumps(result.get("numbers") or {}),
                json.dumps({"flags": result.get("flags") or [],
                            "concordance": result.get("concordance"),
                            "concordance_why": result.get("concordance_why") or ""}),
                int(result.get("grade") or 5),
                result.get("status") or "ok",
            ),
        )
        get_conn().commit()
        return check_id
    except pymysql.err.ProgrammingError:
        return None
    except pymysql.err.IntegrityError:
        get_conn().rollback()
        row = _load_by_url(url) if url else None
        return row["id"] if row else None
    except Exception:
        current_app.logger.exception("claim_checks insert failed")
        return None


def _row_to_view(row):
    def _json(key, default):
        try:
            data = json.loads(row.get(key) or "")
        except (TypeError, ValueError):
            return default
        return data if isinstance(data, type(default)) else default

    study_blob = _json("study_json", {})
    flags_blob = _json("flags_json", {})
    return {
        "id": row.get("id"),
        "status": row.get("status") or "ok",
        "headline": row.get("headline") or "",
        "source_url": row.get("source_url"),
        "claim": _json("claim_json", {}),
        "study": study_blob.get("study") or None,
        "fields": study_blob.get("fields") or {},
        "numbers": _json("numbers_json", {}),
        "flags": flags_blob.get("flags") or [],
        "concordance": flags_blob.get("concordance"),
        "concordance_why": flags_blob.get("concordance_why") or "",
        "grade": int(row.get("grade") or 5),
        "created_at": row.get("created_at"),
    }


def _load(check_id):
    try:
        row = query("SELECT * FROM claim_checks WHERE id = %s", (int(check_id),), one=True)
    except pymysql.err.ProgrammingError:
        return None
    return _row_to_view(row) if row else None


def _load_by_url(url):
    try:
        row = query("SELECT * FROM claim_checks WHERE url_hash = %s",
                    (claim_mod.url_hash(url),), one=True)
    except pymysql.err.ProgrammingError:
        return None
    return _row_to_view(row) if row else None


def _view(result, check_id=None):
    """Card view-model from a fresh pipeline result."""
    v = dict(result)
    v["id"] = check_id
    v["created_at"] = datetime.now(timezone.utc)
    return v


def _decorate(view):
    """Attach the display-only derived bits the partial needs."""
    view["grade_label"] = claim_mod.GRAIN_LABELS.get(view["grade"], "")
    view["flag_labels"] = claim_mod.FLAG_LABELS
    view["citation"] = claim_mod.citation_label(view.get("study"))
    view["study_url"] = claim_mod.study_url(view.get("study"))
    view["permalink"] = (url_for("claim.view", check_id=view["id"], _external=True)
                         if view.get("id") else None)
    view["disclaimer"] = DISCLAIMER
    return view


def _render_page(*, view=None, error=None, hold=False, url_draft="", text_draft=""):
    return render_template(
        "claim.html",
        check=_decorate(view) if view else None,
        error=error, hold=hold,
        url_draft=url_draft, text_draft=text_draft,
        claim_enabled=bool(current_app.config.get("CLAIM_ENABLED", True)),
        disclaimer=DISCLAIMER,
    )


def _respond(*, view=None, error=None, hold=False, url_draft="", text_draft=""):
    if request.headers.get("HX-Request"):
        return render_template(
            "partials/claim_result.html",
            check=_decorate(view) if view else None, error=error, hold=hold)
    return _render_page(view=view, error=error, hold=hold,
                        url_draft=url_draft, text_draft=text_draft)


def _valid_url(url):
    """Public http(s) URL only. Literal loopback / private / link-local
    hosts are refused so the server-side fetch can't be pointed inward."""
    if not url or len(url) > MAX_URL_CHARS:
        return False
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host or "." not in host:
        return False
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    return ip.is_global


@bp.route("/", methods=["GET"])
def index():
    return _render_page()


@bp.route("/", methods=["POST"])
def submit():
    cfg = current_app.config
    if not cfg.get("CLAIM_ENABLED", True):
        return _respond(error="Claim is currently disabled.")

    url = (request.form.get("url") or "").strip()
    text = (request.form.get("text") or "").strip()
    drafts = {"url_draft": url, "text_draft": text[:MAX_TEXT_CHARS]}

    if url:
        if not _valid_url(url):
            return _respond(error="That doesn't look like a web address. Paste a full "
                                  "http(s) link, or paste the headline and paragraph instead.",
                            **drafts)
        cached = _load_by_url(url)
        if cached:
            return _respond(view=cached)
    elif text:
        if len(text) < MIN_TEXT_CHARS:
            return _respond(error="Paste the headline plus at least a paragraph so there "
                                  "is something to check.", **drafts)
    else:
        return _respond(error="Paste a link or a headline and paragraph.", **drafts)

    if not _ip_limiter().hit(client_ip(request)):
        return _respond(hold=True, error=(
            f"You've checked {_config_int('CLAIM_RATE_PER_IP_HOUR', 10)} headlines this "
            "hour. Try again in a little while."), **drafts)
    if not _daily_cap_ok():
        return _respond(hold=True, error=(
            "Claim has hit today's checking budget. Come back tomorrow."), **drafts)

    if url:
        page = extract_body(url, timeout=8.0)
        if page.get("status") != "ok" or not page.get("body_text"):
            return _respond(error="Couldn't read that page (it may be paywalled or "
                                  "blocked). Paste the headline and paragraph instead.",
                            **drafts)
        headline = page.get("title") or ""
        body = page["body_text"]
        input_kind = "url"
    else:
        headline, body = claim_mod.split_pasted_text(text)
        input_kind = "text"

    model_locate = cfg.get("CLAIM_MODEL_LOCATE") or cfg.get("ANTHROPIC_MODEL", "claude-haiku-4-5")
    model_extract = cfg.get("CLAIM_MODEL_EXTRACT") or model_locate
    try:
        result = run_check(
            headline=headline, body=body,
            api_key=cfg.get("ANTHROPIC_API_KEY", ""),
            model_locate=model_locate, model_extract=model_extract,
            contact_email=cfg.get("CLAIM_CONTACT_EMAIL", ""),
        )
    except LLMUnavailable as e:
        current_app.logger.info("claim.submit LLMUnavailable kind=%s: %s", input_kind, e)
        return _respond(error="Couldn't check this one right now. Try again in a minute.",
                        **drafts)

    _record_llm_usage(result.get("usages"))
    check_id = _save(result, input_kind=input_kind, url=url or None)
    return _respond(view=_view(result, check_id))


@bp.route("/<int:check_id>", methods=["GET"])
def view(check_id):
    v = _load(check_id)
    if not v:
        abort(404)
    return _render_page(view=v)
