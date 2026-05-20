"""Canonical concept-key registry for the root-domain lab landing page.

The lab landing page (``/index.html`` at the repo root, served at
``https://sauce.ai/``) lists product concepts under "Coming soon" with
an up/down vote control on each card. The card *content* (name, pitch,
ordering) is rendered statically by the landing page itself — only the
vote tallies come from the server. This module owns the **allowlist of
valid concept keys** that the vote endpoints accept; adding a card to
the landing page that isn't in this set means its vote button silently
no-ops (POST returns 400).

Pure: no Flask, no DB. Tested by ``tests/test_lab_concepts.py``.
"""
from __future__ import annotations

# Coming-soon concepts shown on the lab landing page. Order is
# preserved on the page itself, not here; this set is purely for vote
# validation. `news` is intentionally absent — it is already live and
# has no vote control.
LAB_CONCEPT_KEYS = frozenset({
    # First wave (PR #101)
    "recipes",
    "travel",
    "money",
    "fit",
    "learn",
    "inbox",
    "stage",
    # Radical / high-leverage wave
    "jar",
    "negotiate",
    "clone",
    "doctor",
    "legal",
    "tax",
    "estate",
    "decide",
    "friend",
    "mirror",
})

VOTE_UP = 1
VOTE_DOWN = -1
VOTE_NONE = 0


def is_valid_concept(key: str) -> bool:
    return isinstance(key, str) and key in LAB_CONCEPT_KEYS


def normalize_vote(raw) -> int:
    """Coerce a vote value from form/JSON into one of +1, -1, 0.

    Accepts the int forms (1, -1, 0) and the string forms ("up", "down",
    "1", "-1", "0", ""). Anything else returns 0 (clear vote).
    """
    if raw is None:
        return VOTE_NONE
    if isinstance(raw, bool):
        return VOTE_NONE
    if isinstance(raw, (int, float)):
        v = int(raw)
        if v >= 1:
            return VOTE_UP
        if v <= -1:
            return VOTE_DOWN
        return VOTE_NONE
    if isinstance(raw, str):
        s = raw.strip().lower()
        if s in ("up", "+1", "1", "upvote"):
            return VOTE_UP
        if s in ("down", "-1", "downvote"):
            return VOTE_DOWN
        return VOTE_NONE
    return VOTE_NONE


def is_valid_voter_token(token: str) -> bool:
    """Voter tokens are 40-hex (matches the unsub-token format already in
    use elsewhere in the codebase). Reject anything else so a hostile
    client can't spam arbitrary IDs into the unique key index."""
    if not isinstance(token, str) or len(token) != 40:
        return False
    return all(c in "0123456789abcdef" for c in token)


def tally_with_you(rows, your_vote: int) -> dict:
    """Reduce a list of (vote,) rows into {up, down, score, you}.

    Pure: takes already-fetched rows (or any iterable of ints/tuples)
    so the route can stay thin and this can be unit-tested without a DB.
    """
    up = 0
    down = 0
    for row in rows:
        v = row[0] if isinstance(row, (tuple, list)) else (row.get("vote") if hasattr(row, "get") else row)
        if v == VOTE_UP:
            up += 1
        elif v == VOTE_DOWN:
            down += 1
    return {"up": up, "down": down, "score": up - down, "you": int(your_vote or 0)}
