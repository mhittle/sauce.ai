"""Tests for the feed-header algorithm switcher de-duplication (BUG-025).

`_dedupe_switcher_rows` is pure (no Flask / no DB) so it runs directly. It
collapses duplicate-named `user_algorithms` rows so the front-page
"Algorithm:" dropdown shows each name once, while still resolving the
active id from the full row set.
"""
from app.routes.feed import _dedupe_switcher_rows


def _rows(*specs):
    # spec: (id, name, is_active). Caller supplies rows already ordered as
    # the SQL does: is_active DESC, updated_at DESC.
    return [{"id": i, "name": n, "is_active": a} for (i, n, a) in specs]


def test_no_duplicates_passes_through():
    rows = _rows((1, "A", 1), (2, "B", 0), (3, "C", 0))
    out, active = _dedupe_switcher_rows(rows)
    assert [r["id"] for r in out] == [1, 2, 3]
    assert active == 1


def test_duplicate_names_collapse_keeping_first():
    rows = _rows((5, "Lefty", 0), (9, "Lefty", 0), (12, "Lefty", 0),
                 (3, "Heady", 0))
    out, active = _dedupe_switcher_rows(rows)
    assert [r["id"] for r in out] == [5, 3]      # first Lefty + the Heady
    assert [r["name"] for r in out] == ["Lefty", "Heady"]
    assert active is None


def test_active_row_is_retained_for_a_duplicated_name():
    # Active "Lefty" sorts first (is_active DESC); the non-active dup is
    # dropped, so the kept row matches active_id and the <option> selects.
    rows = _rows((5, "Lefty", 1), (9, "Lefty", 0))
    out, active = _dedupe_switcher_rows(rows)
    assert [r["id"] for r in out] == [5]
    assert active == 5
    assert active in {r["id"] for r in out}


def test_active_resolves_even_when_its_name_has_duplicates():
    rows = _rows((5, "Lefty", 1), (9, "Lefty", 0), (2, "Palo", 0),
                 (7, "Palo", 0))
    out, active = _dedupe_switcher_rows(rows)
    assert active == 5
    assert [r["name"] for r in out] == ["Lefty", "Palo"]


def test_empty_rows():
    out, active = _dedupe_switcher_rows([])
    assert out == []
    assert active is None
