"""Keyset cursor for the firehose stream (BUG-020).

The firehose orders by ``(classified_at, id)`` DESC. ``classify_pending``
writes bursts of rows that share a one-second ``classified_at``, so a
timestamp-only cursor skips rows on the boundary second — part of the
"firehose doesn't show everything" bug. The keyset adds the ``id``
tiebreak so the live tail and "Load more" never skip or duplicate a row.

Pure / Flask-free / DB-free so it unit-tests in the sandbox (same
convention as ``app/trending.py`` and ``app/profiles.py``). The ``%(...)s``
placeholders are PyMySQL paramstyle — values are bound, never interpolated.
"""


def _int_or_none(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def firehose_cursor_clause(after_ts, after_id, before_ts, before_id):
    """Return ``(sql_fragment, params)`` for the stream WHERE clause.

    - ``after_ts`` + ``after_id``  → rows strictly NEWER than the cursor
      (live tail, prepended).
    - ``before_ts`` + ``before_id`` → rows strictly OLDER than the cursor
      ("Load more", appended).
    - neither, or a malformed/absent id → no cursor: the newest page
      (initial load). ``after`` wins if both are somehow supplied.

    A non-integer id degrades to "no cursor" (newest page) rather than
    raising, so a malformed client request can never 500 the stream.
    """
    aid = _int_or_none(after_id)
    if after_ts and aid is not None:
        return (
            "AND (f.classified_at > %(cur_ts)s "
            "OR (f.classified_at = %(cur_ts)s AND a.id > %(cur_id)s))",
            {"cur_ts": after_ts, "cur_id": aid},
        )

    bid = _int_or_none(before_id)
    if before_ts and bid is not None:
        return (
            "AND (f.classified_at < %(cur_ts)s "
            "OR (f.classified_at = %(cur_ts)s AND a.id < %(cur_id)s))",
            {"cur_ts": before_ts, "cur_id": bid},
        )

    return ("", {})
