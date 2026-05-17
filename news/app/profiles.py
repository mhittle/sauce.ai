"""Pure, Flask-free helpers for named algorithm profiles.

`user_algorithms` already carries `name` + `is_active`, so multiple rows
per user are supported at the schema level with no migration. This module
holds the decision logic the `/algo` profile routes need, kept
import-light so it is unit-testable without pymysql.
"""

MAX_NAME_LEN = 120  # matches user_algorithms.name VARCHAR(120)


def clean_profile_name(raw, *, fallback="Custom"):
    name = (raw or "").strip()
    if not name:
        return fallback
    return name[:MAX_NAME_LEN]


def next_default_name(existing_names, *, base="Custom"):
    """First free name in the series "Custom", "Custom 2", "Custom 3", ...
    given the names already taken (case-insensitive, trimmed)."""
    taken = {(n or "").strip().lower() for n in existing_names}
    if base.lower() not in taken:
        return base
    i = 2
    while f"{base} {i}".lower() in taken:
        i += 1
    return f"{base} {i}"


def pick_promotion(remaining, deleted_id):
    """When the active profile is deleted, choose which profile becomes
    active. `remaining` is an ordered iterable of dicts with at least `id`,
    passed most-recently-active/updated first. Returns the first id that
    isn't `deleted_id`, or None if nothing is left."""
    for p in remaining:
        if p["id"] != deleted_id:
            return p["id"]
    return None
