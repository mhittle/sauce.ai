"""FDA 510(k) clearance counts per condition, from the openFDA device API.

Ranking signal for the directory: how many 510(k) clearances name the
condition. openFDA has no "condition" field, so we count clearances whose
``device_name`` contains any of the condition's search terms (the canonical
name, plus device-name phrasings the LLM planner proposes, e.g. "chest x-ray"
for pneumothorax triage). It's a proxy — see README "Known limits".

https://open.fda.gov/apis/device/510k/
"""
from __future__ import annotations

import logging
from typing import Iterable
from urllib.parse import quote

import requests

API = "https://api.fda.gov/device/510k.json"
_UA = {"User-Agent": "sauce.ai-datasets (+https://sauce.ai)"}
log = logging.getLogger(__name__)


def build_search(terms: Iterable[str]) -> str | None:
    """openFDA search expression: device_name:"t1" OR device_name:"t2" ...

    openFDA uses a literal ``+`` as OR between clauses and ``+`` for spaces
    inside a phrase, so we assemble the query string by hand instead of
    letting ``requests`` percent-encode the ``+``.
    """
    clauses = []
    for t in dict.fromkeys(t.strip().lower() for t in terms if t and t.strip()):
        phrase = "+".join(quote(w, safe="-") for w in t.replace('"', "").split())
        if phrase:
            clauses.append(f'device_name:"{phrase}"')
    return "+".join(clauses) or None


def count_510k(terms: Iterable[str], session: requests.Session | None = None,
               timeout: float = 20) -> int | None:
    """Number of 510(k) clearances matching any term; 0 when openFDA reports
    no matches; None on a network/API failure (caller keeps the old value)."""
    expr = build_search(terms)
    if not expr:
        return 0
    http = session or requests
    try:
        resp = http.get(f"{API}?search={expr}&limit=1", headers=_UA, timeout=timeout)
    except requests.RequestException as exc:
        log.warning("openFDA request failed: %s", exc)
        return None
    if resp.status_code == 404:
        return 0  # openFDA answers "No matches found!" with a 404
    if resp.status_code != 200:
        log.warning("openFDA %s: %s", resp.status_code, resp.text[:200])
        return None
    try:
        return int(resp.json()["meta"]["results"]["total"])
    except (KeyError, ValueError, TypeError):
        return None


def refresh_condition(store, name: str, session: requests.Session | None = None) -> int | None:
    """Recount one condition from its name + planner-curated fda_terms.

    Synonyms are deliberately excluded: they're tuned for dataset search
    ("MS", "collapsed lung"), not device names, and inflate the count."""
    cond = store.get_condition(name)
    if not cond:
        return None
    terms = [cond["name"], *cond["fda_terms"]]
    # Very short terms ("ms", "ich") match unrelated device names.
    terms = [t for t in terms if len(t) >= 4]
    n = count_510k(terms, session=session)
    if n is not None:
        store.set_condition_510k(cond["name"], n)
    return n
