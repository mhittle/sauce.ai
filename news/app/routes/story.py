"""Story dossier at /story/<story_id>.

Aggregates every article in a deduplicated story cluster (set by
classify_pending via `articles.story_id`) and lays them out across the
political-lean spectrum. A short Claude-generated framing summary sits at
the top describing how outlets on different sides framed the story, cached
in `story_dossiers` keyed by the cluster's current member signature.

Visibility honors user-added personal sources: anonymous users see only
global (`sources.owner_id IS NULL`) members; signed-in users additionally
see their own personal feed members. The cluster itself is computed across
all sources globally, but we filter the rendered members to what the
viewer can see — so a personal feed never shows another user's articles.
"""
import hashlib

from flask import Blueprint, abort, current_app, render_template, g

from ..db import query, execute, get_conn
from ..discussion import discussions_for_story
from ..classifier import generate_framing, LLMUnavailable


bp = Blueprint("story", __name__)


LEAN_LEFT_THRESHOLD = -0.2
LEAN_RIGHT_THRESHOLD = 0.2

# Cluster lookback for the dossier page. Wider than feed's 7d window so
# slowly-publishing partner outlets that join a story late still show.
DOSSIER_LOOKBACK_DAYS = 14

FRAMING_MIN_MEMBERS = 3
FRAMING_MIN_BUCKETS = 2


def _lean_bucket(lean):
    if lean is None:
        return "center"
    if lean <= LEAN_LEFT_THRESHOLD:
        return "left"
    if lean >= LEAN_RIGHT_THRESHOLD:
        return "right"
    return "center"


def _member_signature(members):
    """Stable hash of the sorted member ids — invalidates cache when set changes."""
    ids = sorted(int(m["id"]) for m in members)
    return hashlib.sha1(",".join(str(i) for i in ids).encode("utf-8")).hexdigest()


def _lead_paragraph(body_text, summary):
    """Pick a short lead paragraph for a dossier card.

    Prefers the first paragraph of the extracted article body (>=40 chars,
    keeps the prose tone). Falls back to the RSS summary. Truncated to
    ~400 chars in the template.
    """
    if body_text:
        for p in body_text.split("\n"):
            p = p.strip()
            if len(p) >= 40:
                return p
    return (summary or "").strip()


@bp.route("/story/<int:story_id>")
def view(story_id):
    canonical = query(
        "SELECT id, story_id FROM articles WHERE id = %s",
        (story_id,),
        one=True,
    )
    if not canonical:
        abort(404)
    if canonical["story_id"] is not None and canonical["story_id"] != canonical["id"]:
        abort(404)

    u = getattr(g, "user", None)
    uid = u["id"] if u else None
    vis_sql = "(s.owner_id IS NULL OR s.owner_id = %(_vis_owner)s)" if uid else "s.owner_id IS NULL"
    vis_params = {"_vis_owner": uid} if uid else {}

    sql = f"""
      SELECT a.id, a.title, a.url, a.summary, a.thumbnail_url, a.byline,
             a.published_at,
             s.id AS source_id, s.name AS source_name, s.source_lean,
             f.political_lean, f.objectivity, f.category,
             b.body_text
      FROM articles a
      JOIN sources s ON s.id = a.source_id
      LEFT JOIN article_features f ON f.article_id = a.id
      LEFT JOIN article_bodies b ON b.article_id = a.id
      WHERE a.story_id = %(story_id)s
        AND a.status = 'classified'
        AND a.published_at >= UTC_TIMESTAMP() - INTERVAL %(lookback)s DAY
        AND {vis_sql}
      ORDER BY a.published_at ASC
    """
    members = query(sql, {"story_id": story_id, "lookback": DOSSIER_LOOKBACK_DAYS, **vis_params})

    if not members or len(members) < 2:
        abort(404)

    buckets = {"left": [], "center": [], "right": []}
    for m in members:
        m["lead"] = _lead_paragraph(m.get("body_text"), m.get("summary"))
        m["bucket"] = _lean_bucket(m.get("political_lean"))
        buckets[m["bucket"]].append(m)

    distinct_buckets = sum(1 for v in buckets.values() if v)
    eligible = len(members) >= FRAMING_MIN_MEMBERS and distinct_buckets >= FRAMING_MIN_BUCKETS

    framing = None
    if eligible:
        framing = _get_or_generate_framing(story_id, members)

    canonical_member = next((m for m in members if m["id"] == story_id), members[0])
    discussions = discussions_for_story([m["id"] for m in members])

    return render_template(
        "story.html",
        story_id=story_id,
        canonical=canonical_member,
        members=members,
        buckets=buckets,
        discussions=discussions,
        framing=framing,
        framing_eligible=eligible,
        framing_min_members=FRAMING_MIN_MEMBERS,
        framing_min_buckets=FRAMING_MIN_BUCKETS,
    )


def _get_or_generate_framing(story_id, members):
    """Return cached framing summary or generate one and cache it.

    Returns None when the LLM is unavailable (no API key, network error,
    parse error) — the dossier page renders without a framing block in
    that case.
    """
    sig = _member_signature(members)
    cached = query(
        "SELECT summary_text, member_signature FROM story_dossiers WHERE story_id = %s",
        (story_id,),
        one=True,
    )
    if cached and cached["member_signature"] == sig:
        return cached["summary_text"]

    cfg = current_app.config
    payload = [
        {
            "source_name": m["source_name"],
            "source_lean": m.get("source_lean") or 0.0,
            "political_lean": m.get("political_lean") or 0.0,
            "title": m["title"],
            "lead": m.get("lead") or "",
        }
        for m in members
    ]
    try:
        result = generate_framing(
            payload,
            api_key=cfg.get("ANTHROPIC_API_KEY", ""),
            model=cfg.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"),
        )
    except LLMUnavailable:
        return None

    summary = result["summary"]
    lean_buckets = "".join(
        c for c, present in (
            ("L", any(_lean_bucket(m.get("political_lean")) == "left" for m in members)),
            ("C", any(_lean_bucket(m.get("political_lean")) == "center" for m in members)),
            ("R", any(_lean_bucket(m.get("political_lean")) == "right" for m in members)),
        ) if present
    )
    execute(
        """INSERT INTO story_dossiers
             (story_id, member_signature, summary_text, article_count, lean_buckets, model)
           VALUES (%s, %s, %s, %s, %s, %s)
           ON DUPLICATE KEY UPDATE
             member_signature = VALUES(member_signature),
             summary_text     = VALUES(summary_text),
             article_count    = VALUES(article_count),
             lean_buckets     = VALUES(lean_buckets),
             model            = VALUES(model)""",
        (story_id, sig, summary, len(members), lean_buckets, result["usage"].get("model", "")),
    )
    get_conn().commit()
    return summary
