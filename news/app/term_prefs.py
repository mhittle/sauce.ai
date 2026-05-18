"""Per-user keyword mute & boost — pure SQL-fragment builders.

Flask-free (mirrors `app.discussion` / `app.trending` / `app.ranking`):
no DB, no request context, so it unit-tests like `build_filters_sql`.

A user keeps two disjoint term lists:
  - **mute**  — a hard filter: any article whose title+summary contains
    the term is dropped from the feed entirely.
  - **boost** — a score multiplier: a matching article's score is
    multiplied by the term's weight (the strongest matching boost wins;
    boosts do not compound).

Matching is case-insensitive plain substring against
`title + ' ' + summary` (v1; entity/phrase-aware matching is the
roadmapped v2 once topic extraction lands). LIKE metacharacters in the
user term are escaped so they match literally.
"""

# Match surface: the article title plus its summary. Kept here so the
# feed query and this builder cannot drift.
_MATCH_EXPR = "LOWER(CONCAT(a.title, ' ', COALESCE(a.summary, '')))"

MIN_TERM_LEN = 2
MAX_TERM_LEN = 128

# Boost multiplier bounds. 1.0 = neutral (no boost); the default a new
# boost term gets is 1.5. Clamp keeps a runaway value from drowning the
# rest of the algorithm.
BOOST_MIN = 1.0
BOOST_MAX = 5.0
BOOST_DEFAULT = 1.5

VALID_MODES = ("mute", "boost")


def normalize_term(raw):
    """Lowercase, trim, collapse internal whitespace; bound the length.

    Returns the cleaned term, or None if it's empty or too short to be a
    useful filter (a 1-char term would match almost everything)."""
    if raw is None:
        return None
    t = " ".join(str(raw).split()).strip().lower()
    if len(t) < MIN_TERM_LEN:
        return None
    return t[:MAX_TERM_LEN]


def clamp_boost(raw):
    try:
        w = float(raw)
    except (TypeError, ValueError):
        return BOOST_DEFAULT
    if w < BOOST_MIN:
        return BOOST_MIN
    if w > BOOST_MAX:
        return BOOST_MAX
    return w


def escape_like(term):
    """Escape LIKE metacharacters so the term matches literally.

    Order matters: the backslash must be doubled first so the escapes we
    add for % and _ aren't themselves re-escaped."""
    return (
        term.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def build_term_clauses(prefs):
    """Build the mute filter + boost multiplier from a user's term rows.

    `prefs` is an iterable of mappings with `term`, `mode`, and (for
    boosts) `weight`. Returns `(mute_sql, boost_expr, params)`:

      - `mute_sql`   — "" or a string of ` AND NOT (...)` clauses to
                        append to the feed WHERE.
      - `boost_expr` — "" or a `GREATEST(1.0, CASE ... )` expression; the
                        caller multiplies the score by `(boost_expr)`. A
                        non-matching article evaluates to the 1.0 floor
                        (neutral); a match yields the term's weight; the
                        strongest matching boost wins (no compounding).
      - `params`     — bind params for both fragments.

    Terms are normalized and de-duplicated; an empty/short term is
    skipped. If the same term somehow appears in both lists, mute wins
    (the safer, more conservative outcome for the reader)."""
    muted = {}
    boosted = {}
    for p in prefs or ():
        term = normalize_term(p["term"])
        if term is None:
            continue
        mode = p["mode"]
        if mode == "mute":
            muted[term] = True
        elif mode == "boost":
            boosted[term] = clamp_boost(p.get("weight"))

    for term in muted:
        boosted.pop(term, None)

    params = {}
    mute_clauses = []
    for i, term in enumerate(sorted(muted)):
        key = f"term_mute_{i}"
        params[key] = f"%{escape_like(term)}%"
        mute_clauses.append(
            f"NOT ({_MATCH_EXPR} LIKE %({key})s ESCAPE '\\\\')"
        )
    mute_sql = (" AND " + " AND ".join(mute_clauses)) if mute_clauses else ""

    boost_cases = []
    for i, (term, weight) in enumerate(sorted(boosted.items())):
        pkey = f"term_boost_{i}"
        wkey = f"term_boost_w_{i}"
        params[pkey] = f"%{escape_like(term)}%"
        params[wkey] = weight
        boost_cases.append(
            f"CASE WHEN {_MATCH_EXPR} LIKE %({pkey})s ESCAPE '\\\\' "
            f"THEN %({wkey})s ELSE 0 END"
        )
    boost_expr = (
        f"GREATEST(1.0, {', '.join(boost_cases)})" if boost_cases else ""
    )

    return mute_sql, boost_expr, params
