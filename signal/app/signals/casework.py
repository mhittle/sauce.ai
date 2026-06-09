"""Casework / cabinetry classifier (the core fit signal for bids + permits).

Triage, not perfection: flag solicitations whose text (title + description +
extracted bid-package text) *definitively* references cabinetry/casework, and
score the rest. A "strong" term sets the flag; weak terms only nudge the score.
Pure stdlib so it's unit-testable on text fixtures.

Strong terms include CSI section numbers where architectural woodwork /
manufactured casework live (06 40/06 41, 12 30/12 35).
"""
from __future__ import annotations

import re

STRONG_TERMS = (
    "casework", "cabinet", "cabinetry", "cabinets", "millwork",
    "architectural woodwork", "manufactured casework", "plastic laminate",
    "base cabinet", "wall cabinet", "upper cabinet", "lower cabinet",
    "countertop", "counter top", "vanity", "vanities", "ff&e", "ffe",
    "06 40", "06 41", "064000", "064100", "12 30", "12 35", "123000", "123500",
)
WEAK_TERMS = (
    "laminate", "joinery", "shop drawing", "casegood", "casegoods",
    "wood shelving", "built-in", "built in", "fixtures and furnishings",
)


def _present(term: str, text: str) -> bool:
    # word-ish boundary for short alpha terms to avoid e.g. "cabinet" in nothing
    if term.replace(" ", "").isalpha() and len(term) <= 7:
        return re.search(rf"\b{re.escape(term)}\b", text) is not None
    return term in text


def classify_casework(text: str | None) -> dict:
    """Return {flag, score, matches}. flag = any strong term present."""
    if not text:
        return {"flag": False, "score": 0.0, "matches": []}
    low = text.lower()
    strong = [t for t in STRONG_TERMS if _present(t, low)]
    weak = [t for t in WEAK_TERMS if _present(t, low)]
    score = min(1.0, round(0.34 * len(set(strong)) + 0.08 * len(set(weak)), 3))
    return {"flag": bool(strong), "score": score,
            "matches": sorted(set(strong) | set(weak))}
