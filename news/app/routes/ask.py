"""Ask your feed — grounded conversational news over the user's corpus.

A signed-in chat surface that retrieves from the reader's *visible +
un-muted* corpus (FULLTEXT search + the feed's source-visibility and
profile-mute rules) and grounds one Haiku call on the retrieved
articles with inline citations. Same request-path class as
`algo.describe`: synchronous user-initiated LLM call, single-flight,
daily-capped, no automatic / per-request spawn.

The pure helpers live in `app.ask` (no Flask/DB/Haiku) so tests don't
need the SDK; this module is the Flask glue.
"""
import json
import secrets
from datetime import datetime, timezone

import pymysql
from flask import (
    Blueprint, current_app, g, render_template, request, url_for,
)

from .. import ask as ask_mod
from ..auth import login_required
from ..classifier import LLMUnavailable
from ..db import execute, get_conn, query
from ..ratelimit import SlidingWindowLimiter
from ..term_prefs import build_term_clauses

bp = Blueprint("ask", __name__)


_HOLD_REASON_RATELIMIT = "ratelimit"
_HOLD_REASON_TABLE_MISSING = "table-missing"


def _now_utc():
    return datetime.now(timezone.utc)


def _utc_midnight(ts=None):
    ts = ts or _now_utc()
    return ts.replace(hour=0, minute=0, second=0, microsecond=0)


def _config_int(key, default):
    val = current_app.config.get(key)
    try:
        return int(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def _mute_terms_for_active_algo(user_id):
    """Read the user's active-profile mute terms and return a `(mute_sql,
    params)` fragment ready to append to the retrieval WHERE — same
    semantics as the feed's mute, just without the boost expression. An
    empty list returns `("", {})`."""
    try:
        rows = query(
            "SELECT atp.term, atp.mode, atp.weight "
            "FROM algorithm_term_prefs atp "
            "JOIN user_algorithms ua ON ua.id = atp.algorithm_id "
            "WHERE ua.user_id = %s AND ua.is_active = 1 AND atp.mode = 'mute'",
            (user_id,),
        )
    except pymysql.err.ProgrammingError:
        return "", {}
    mute_sql, _boost_expr, params = build_term_clauses(rows or [])
    return mute_sql, params


def _retrieve(user_id, terms, *, window_days, limit):
    """Run the personalized FULLTEXT retrieval. Same visibility / source-
    pref / mute-keyword rules as the feed; canonical members only
    (deduped to one row per story cluster); takes the top by relevance
    then recency. Caller already short-circuited the empty-terms case."""
    mute_sql, mute_params = _mute_terms_for_active_algo(user_id)
    sql = f"""
      SELECT a.id, a.title, a.summary, a.url, a.published_at,
             a.story_id, s.name AS source_name,
             f.political_lean, f.category,
             MATCH (a.title, a.summary) AGAINST (%(q)s) AS relevance
      FROM articles a
      JOIN sources s ON s.id = a.source_id
      LEFT JOIN article_features f ON f.article_id = a.id
      LEFT JOIN user_source_prefs usp
        ON usp.user_id = %(uid)s AND usp.source_id = s.id
      WHERE a.status = 'classified'
        AND (a.story_id IS NULL OR a.id = a.story_id)
        AND (s.owner_id IS NULL OR s.owner_id = %(uid)s)
        AND COALESCE(usp.weight, 1.0) > 0
        AND a.published_at >= UTC_TIMESTAMP() - INTERVAL %(window_days)s DAY
        AND MATCH (a.title, a.summary) AGAINST (%(q)s)
        {mute_sql}
      ORDER BY relevance DESC, a.published_at DESC
      LIMIT %(limit)s
    """
    params = {
        "q": terms,
        "uid": user_id,
        "window_days": int(window_days),
        "limit": int(limit),
        **mute_params,
    }
    return query(sql, params) or []


def _conversation_history(conversation, user_id, max_turns):
    """Load the prior turns of one conversation for this user (oldest
    first). Tolerates the `ask_queries` table being absent — the route
    still works pre-migration."""
    if not conversation:
        return []
    try:
        rows = query(
            "SELECT question, answer_text FROM ask_queries "
            "WHERE conversation = %s AND user_id = %s "
            "ORDER BY id ASC LIMIT %s",
            (conversation, user_id, int(max_turns) * 2),
        )
    except pymysql.err.ProgrammingError:
        return []
    return ask_mod.serialize_history(rows or [])


def _record_llm_usage(usage):
    """Best-effort `llm_usage` write — same shape as the
    breaking-alerts / classify writers. Never propagates a failure."""
    if not usage:
        return
    try:
        execute(
            "INSERT INTO llm_usage (model, input_tokens, output_tokens, "
            "cache_read_tokens, articles, est_cost_usd) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                usage.get("model"),
                int(usage.get("input_tokens", 0)),
                int(usage.get("output_tokens", 0)),
                int(usage.get("cache_read_tokens", 0)),
                1,
                float(usage.get("est_cost_usd", 0.0)),
            ),
        )
    except Exception:
        pass


def _record_query(user_id, conversation, question, answer_payload, citations,
                  answered):
    """Persist one `ask_queries` row. Tolerates the table being absent
    pre-migration: the in-process limiter still enforces the daily cap so
    the page stays functional. Returns True on success."""
    try:
        execute(
            "INSERT INTO ask_queries (user_id, conversation, question, "
            "answered, article_ids, answer_text) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                int(user_id),
                conversation or "",
                question[:2000],
                1 if answered else 0,
                ",".join(str(int(c)) for c in (citations or [])[:50])[:500],
                answer_payload[:8000],
            ),
        )
        get_conn().commit()
        return True
    except pymysql.err.ProgrammingError:
        return False
    except Exception:
        current_app.logger.exception("ask_queries insert failed")
        return False


def _today_count(user_id):
    """Number of `ask_queries` rows already logged today (UTC) for the
    daily-cap check. Falls back to the in-process sliding limiter when the
    table is absent — see `_fallback_limiter`."""
    try:
        row = query(
            "SELECT COUNT(*) AS n FROM ask_queries "
            "WHERE user_id = %s AND created_at >= %s",
            (user_id, _utc_midnight()),
            one=True,
        )
    except pymysql.err.ProgrammingError:
        return None
    return int(row["n"]) if row else 0


def _fallback_limiter():
    """Per-worker daily limiter used only when `ask_queries` is missing.
    Reused across requests via `current_app.extensions`. Per-worker means
    the actual ceiling is N_workers * cap until the migration lands —
    acceptable for the brief migrate-after-deploy window."""
    ext = current_app.extensions
    lim = ext.get("ask_limiter")
    if lim is None:
        max_per_day = _config_int("ASK_MAX_PER_DAY", ask_mod.DEFAULT_MAX_PER_DAY)
        lim = SlidingWindowLimiter(max_per_day, 24 * 60 * 60)
        ext["ask_limiter"] = lim
    return lim


def _render_chat(*, conversation, turns, error=None, hold_reason=None,
                 question_draft=""):
    """Render the full chat page. `turns` is a list of pre-built turn
    dicts (one per assistant reply already in the conversation)."""
    return render_template(
        "ask.html",
        conversation=conversation,
        turns=turns,
        error=error,
        hold_reason=hold_reason,
        question_draft=question_draft,
        max_per_day=_config_int("ASK_MAX_PER_DAY", ask_mod.DEFAULT_MAX_PER_DAY),
        ask_enabled=bool(current_app.config.get("ASK_ENABLED", True)),
    )


def _replay_turns(conversation, user_id):
    """Reconstruct the visible chat transcript from persisted rows for a
    GET-revisit. Citations are stored as a comma-joined string of article
    ids; we look those up to render the footnote links."""
    if not conversation:
        return []
    try:
        rows = query(
            "SELECT question, answer_text, article_ids, answered "
            "FROM ask_queries WHERE conversation = %s AND user_id = %s "
            "ORDER BY id ASC LIMIT 50",
            (conversation, user_id),
        )
    except pymysql.err.ProgrammingError:
        return []
    turns = []
    for r in rows or []:
        payload = r.get("answer_text") or ""
        answer = payload
        citations = []
        if payload.startswith("{"):
            try:
                parsed = json.loads(payload)
                answer = parsed.get("answer", "") or ""
                cites = parsed.get("citations") or []
                citations = [_resolve_citation(c) for c in cites]
                citations = [c for c in citations if c]
            except (TypeError, ValueError):
                pass
        turns.append({
            "question": r.get("question") or "",
            "answer": answer,
            "answered": bool(r.get("answered")),
            "citations": citations,
        })
    return turns


def _resolve_citation(cite):
    """Look up one cited article id for rendering. Returns a small dict
    with the source / title / link the partial expects, or None if the
    article has since been pruned."""
    try:
        article_id = int(cite.get("article_id") if isinstance(cite, dict) else cite)
    except (TypeError, ValueError):
        return None
    row = query(
        "SELECT a.id, a.title, a.url, a.story_id, s.name AS source_name "
        "FROM articles a JOIN sources s ON s.id = a.source_id "
        "WHERE a.id = %s",
        (article_id,), one=True,
    )
    if not row:
        return None
    number = cite.get("number") if isinstance(cite, dict) else None
    return {
        "number": int(number) if number else None,
        "article_id": row["id"],
        "title": row["title"],
        "source_name": row["source_name"],
        "url": row["url"],
        "story_url": (url_for("story.view", story_id=row["story_id"])
                      if row.get("story_id") else None),
    }


def _build_citation_links(articles, citations):
    """For the freshly-rendered turn, turn the in-order numeric citations
    `parse_answer` returned into the same dict shape as `_resolve_citation`
    so the partial can render the footnotes."""
    out = []
    for n in citations:
        try:
            idx = int(n) - 1
        except (TypeError, ValueError):
            continue
        if idx < 0 or idx >= len(articles):
            continue
        a = articles[idx]
        out.append({
            "number": int(n),
            "article_id": a.get("id"),
            "title": a.get("title"),
            "source_name": a.get("source_name"),
            "url": a.get("url"),
            "story_url": (url_for("story.view", story_id=a["story_id"])
                          if a.get("story_id") else None),
        })
    return out


def _serialize_answer_payload(answer, citation_links):
    """Pack the user-visible answer + the link metadata we'll need to
    re-render the citations on a later GET revisit, into one JSON blob for
    `ask_queries.answer_text`. (We only persist the ids + numbers; the
    title/url get re-fetched on revisit so a renamed source stays correct.)"""
    cites = [
        {"number": c.get("number"), "article_id": c.get("article_id")}
        for c in (citation_links or [])
        if c.get("article_id")
    ]
    return json.dumps({"answer": answer, "citations": cites})


@bp.route("/", methods=["GET"])
@login_required
def index():
    if not current_app.config.get("ASK_ENABLED", True):
        return _render_chat(conversation="", turns=[],
                            error="Ask is currently disabled.")
    conversation = (request.args.get("c") or "").strip()[:40]
    turns = _replay_turns(conversation, g.user["id"]) if conversation else []
    return _render_chat(conversation=conversation, turns=turns)


@bp.route("/", methods=["POST"])
@login_required
def submit():
    if not current_app.config.get("ASK_ENABLED", True):
        return _render_chat(conversation="", turns=[],
                            error="Ask is currently disabled.")
    user_id = g.user["id"]
    cfg = current_app.config

    question = (request.form.get("question") or "").strip()
    conversation = (request.form.get("conversation") or "").strip()[:40]
    if not conversation:
        conversation = secrets.token_hex(20)

    prior_turns = _replay_turns(conversation, user_id)

    if not question:
        return _render_chat(
            conversation=conversation, turns=prior_turns,
            error="Type a question to ask your feed.")

    # Daily-cap gate — DB-backed when the table is present, in-process
    # fallback otherwise. `today_count is None` is the missing-table signal.
    max_per_day = _config_int("ASK_MAX_PER_DAY", ask_mod.DEFAULT_MAX_PER_DAY)
    today_count = _today_count(user_id)
    if today_count is None:
        if not _fallback_limiter().hit(f"u{user_id}"):
            return _render_chat(
                conversation=conversation, turns=prior_turns,
                question_draft=question,
                hold_reason=_HOLD_REASON_RATELIMIT,
                error=(f"You've reached today's Ask limit ({max_per_day}). "
                       "Come back tomorrow."))
    else:
        if not ask_mod.daily_cap_ok(today_count, max_per_day):
            return _render_chat(
                conversation=conversation, turns=prior_turns,
                question_draft=question,
                hold_reason=_HOLD_REASON_RATELIMIT,
                error=(f"You've reached today's Ask limit ({max_per_day}). "
                       "Come back tomorrow."))

    # Reduce the question to its content terms before MATCH AGAINST —
    # interrogatives/stopwords would otherwise dominate the FULLTEXT match.
    terms = ask_mod.query_terms(question)
    if not terms:
        return _answer_with_no_coverage(
            conversation, prior_turns, question, user_id,
            "I don't have coverage of that in your feed — try naming a "
            "specific topic, person, or place.",
        )

    window_days = _config_int("ASK_WINDOW_DAYS", ask_mod.DEFAULT_WINDOW_DAYS)
    max_articles = _config_int("ASK_MAX_CONTEXT_ARTICLES",
                               ask_mod.DEFAULT_MAX_CONTEXT_ARTICLES)
    articles = _retrieve(user_id, terms,
                         window_days=window_days, limit=max_articles)
    if not articles:
        return _answer_with_no_coverage(
            conversation, prior_turns, question, user_id,
            "I don't have coverage of that in your feed.",
        )

    history_pairs = _conversation_history(
        conversation, user_id,
        max_turns=_config_int("ASK_MAX_TURNS", ask_mod.DEFAULT_MAX_TURNS),
    )

    model = cfg.get("ASK_MODEL") or cfg.get(
        "ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    try:
        result = ask_mod.ask_feed(
            question, history_pairs, articles,
            api_key=cfg.get("ANTHROPIC_API_KEY", ""),
            model=model,
        )
    except LLMUnavailable:
        current_app.logger.info("ask.submit LLMUnavailable q_len=%d", len(question))
        return _render_chat(
            conversation=conversation, turns=prior_turns,
            question_draft=question,
            error="Couldn't reach the model right now. Try again in a "
                  "minute.")

    _record_llm_usage(result.get("usage"))

    citation_links = _build_citation_links(articles, result["citations"])
    payload = _serialize_answer_payload(result["answer"], citation_links)
    _record_query(
        user_id, conversation, question, payload,
        [c["article_id"] for c in citation_links if c.get("article_id")],
        result["answered"],
    )

    new_turn = {
        "question": question,
        "answer": result["answer"],
        "answered": result["answered"],
        "citations": citation_links,
    }
    if request.headers.get("HX-Request"):
        return render_template(
            "partials/ask_answer.html",
            turn=new_turn, conversation=conversation,
        )
    return _render_chat(
        conversation=conversation, turns=prior_turns + [new_turn],
    )


def _answer_with_no_coverage(conversation, prior_turns, question, user_id, msg):
    """The retrieval-empty / all-stopword short-circuit. No LLM call —
    the prompt's anti-hallucination instruction is moot when there's no
    context to ground on. We still persist the row so it counts toward
    today's audit + history."""
    payload = json.dumps({"answer": msg, "citations": []})
    _record_query(user_id, conversation, question, payload, [], False)
    new_turn = {
        "question": question,
        "answer": msg,
        "answered": False,
        "citations": [],
    }
    if request.headers.get("HX-Request"):
        return render_template(
            "partials/ask_answer.html",
            turn=new_turn, conversation=conversation,
        )
    return _render_chat(
        conversation=conversation, turns=prior_turns + [new_turn],
    )
