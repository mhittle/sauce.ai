"""Lab landing-page voting endpoints (anon, aggregate, per-browser).

The root-domain landing page at ``https://sauce.ai/`` is a static
``index.html`` that shows up/down vote controls on each "Coming soon"
product card. These endpoints back those controls:

- ``GET  /labvotes/tally``  -> ``{tally: {key: {up,down,score,you}}, voter_token: str}``
- ``POST /labvotes/vote``   -> ``{up, down, score, you}`` for that key

Same-origin (``sauce.ai`` and ``sauce.ai/news`` share the host, so
cookies set with default ``Path=/`` are visible to both surfaces). No
auth: voting is anonymous, identity is a 40-hex token in the
``lab_voter_token`` cookie. CSRF is exempt for ``lab.vote`` (anon
endpoint, low-stakes, the per-voter UNIQUE index caps abuse from any
single cookie).

A missing ``lab_concept_votes`` table only 500s these endpoints — the
rest of the news app is unaffected (not BUG-007 class). The landing
page's JS catches errors and hides the vote UI quietly, so visitors
still see the cards.
"""
from __future__ import annotations

import secrets

from flask import Blueprint, jsonify, make_response, request

from ..db import execute, get_conn, query
from ..lab_concepts import (
    LAB_CONCEPT_KEYS,
    VOTE_NONE,
    is_valid_concept,
    is_valid_voter_token,
    normalize_vote,
    tally_with_you,
)

bp = Blueprint("lab", __name__)

VOTER_COOKIE = "lab_voter_token"
VOTER_COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # 1 year


def _read_or_mint_voter_token():
    """Return (token, freshly_minted). If the cookie was missing or
    malformed, generate a new 40-hex token to set on the response."""
    cookie = request.cookies.get(VOTER_COOKIE, "")
    if is_valid_voter_token(cookie):
        return cookie, False
    return secrets.token_hex(20), True


def _set_voter_cookie(resp, token):
    resp.set_cookie(
        VOTER_COOKIE,
        token,
        max_age=VOTER_COOKIE_MAX_AGE,
        path="/",
        samesite="Lax",
        secure=request.is_secure,
        httponly=False,
    )


def _fetch_aggregate():
    """All counts grouped by (concept_key, vote). Returns
    {key: {up, down}} for every key currently in the table."""
    rows = query(
        "SELECT concept_key, vote, COUNT(*) AS n "
        "FROM lab_concept_votes "
        "GROUP BY concept_key, vote"
    )
    agg = {}
    for r in rows:
        slot = agg.setdefault(r["concept_key"], {"up": 0, "down": 0})
        if r["vote"] == 1:
            slot["up"] += int(r["n"])
        elif r["vote"] == -1:
            slot["down"] += int(r["n"])
    return agg


def _fetch_your_votes(voter_token):
    rows = query(
        "SELECT concept_key, vote FROM lab_concept_votes WHERE voter_token = %s",
        (voter_token,),
    )
    return {r["concept_key"]: int(r["vote"]) for r in rows}


def _full_tally(voter_token):
    agg = _fetch_aggregate()
    yours = _fetch_your_votes(voter_token)
    tally = {}
    for key in LAB_CONCEPT_KEYS:
        slot = agg.get(key, {"up": 0, "down": 0})
        tally[key] = {
            "up": slot["up"],
            "down": slot["down"],
            "score": slot["up"] - slot["down"],
            "you": yours.get(key, 0),
        }
    return tally


@bp.route("/labvotes/tally", methods=["GET"])
def tally():
    voter_token, fresh = _read_or_mint_voter_token()
    payload = {"tally": _full_tally(voter_token), "voter_token": voter_token}
    resp = make_response(jsonify(payload))
    if fresh:
        _set_voter_cookie(resp, voter_token)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/labvotes/vote", methods=["POST"])
def vote():
    data = request.get_json(silent=True) or request.form
    key = (data.get("concept_key") or "").strip()
    if not is_valid_concept(key):
        return jsonify({"error": "unknown concept_key"}), 400

    v = normalize_vote(data.get("vote"))

    voter_token, fresh = _read_or_mint_voter_token()

    if v == VOTE_NONE:
        execute(
            "DELETE FROM lab_concept_votes WHERE concept_key = %s AND voter_token = %s",
            (key, voter_token),
        )
    else:
        execute(
            "INSERT INTO lab_concept_votes (concept_key, voter_token, vote) "
            "VALUES (%s, %s, %s) "
            "ON DUPLICATE KEY UPDATE vote = VALUES(vote), updated_at = CURRENT_TIMESTAMP",
            (key, voter_token, v),
        )
    get_conn().commit()

    rows = query(
        "SELECT vote FROM lab_concept_votes WHERE concept_key = %s",
        (key,),
    )
    counts = tally_with_you([(r["vote"],) for r in rows], v)
    resp = make_response(jsonify(counts))
    if fresh:
        _set_voter_cookie(resp, voter_token)
    resp.headers["Cache-Control"] = "no-store"
    return resp
