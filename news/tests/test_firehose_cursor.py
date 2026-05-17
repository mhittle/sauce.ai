"""Tests for the firehose keyset cursor (BUG-020).

Pure helper, no Flask/PyMySQL — runs in the sandbox (same convention as
test_feed_sort's pure-helper imports, but from a Flask-free module).
"""
from app.firehose_cursor import firehose_cursor_clause


def test_no_cursor_returns_empty():
    sql, params = firehose_cursor_clause(None, None, None, None)
    assert sql == ""
    assert params == {}


def test_after_cursor_is_strictly_newer_with_id_tiebreak():
    sql, params = firehose_cursor_clause("2026-05-17 10:00:00", "42", None, None)
    assert "f.classified_at > %(cur_ts)s" in sql
    assert "f.classified_at = %(cur_ts)s AND a.id > %(cur_id)s" in sql
    assert sql.startswith("AND (")
    assert params == {"cur_ts": "2026-05-17 10:00:00", "cur_id": 42}


def test_before_cursor_is_strictly_older_with_id_tiebreak():
    sql, params = firehose_cursor_clause(None, None, "2026-05-17 09:00:00", "7")
    assert "f.classified_at < %(cur_ts)s" in sql
    assert "f.classified_at = %(cur_ts)s AND a.id < %(cur_id)s" in sql
    assert params == {"cur_ts": "2026-05-17 09:00:00", "cur_id": 7}


def test_after_wins_when_both_supplied():
    sql, params = firehose_cursor_clause("2026-05-17 10:00:00", "42",
                                         "2026-05-17 09:00:00", "7")
    assert "a.id > %(cur_id)s" in sql
    assert params == {"cur_ts": "2026-05-17 10:00:00", "cur_id": 42}


def test_id_is_coerced_to_int():
    _, params = firehose_cursor_clause("2026-05-17 10:00:00", "42", None, None)
    assert params["cur_id"] == 42 and isinstance(params["cur_id"], int)


def test_malformed_after_id_degrades_to_no_cursor():
    # A bad client request must not 500 the stream — it falls back to the
    # newest page rather than emitting a clause with a junk id.
    for bad in ("abc", "", "1.5", None, "12; DROP TABLE articles"):
        assert firehose_cursor_clause("2026-05-17 10:00:00", bad, None, None) == ("", {})


def test_after_ts_without_id_is_no_cursor():
    assert firehose_cursor_clause("2026-05-17 10:00:00", None, None, None) == ("", {})


def test_before_ts_without_id_is_no_cursor():
    assert firehose_cursor_clause(None, None, "2026-05-17 09:00:00", None) == ("", {})


def test_empty_after_ts_falls_through_to_before():
    sql, params = firehose_cursor_clause("", "42", "2026-05-17 09:00:00", "7")
    assert "f.classified_at < %(cur_ts)s" in sql
    assert params == {"cur_ts": "2026-05-17 09:00:00", "cur_id": 7}
