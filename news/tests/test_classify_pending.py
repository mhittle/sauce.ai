"""Unit tests for the BUG-016..019 changes in jobs/classify_pending.py.

Covers the pure version-tagging helper, the journalist first_seen seeding,
and the bounded -nollm reclassify pass. DB access is faked with a scripted
cursor (same approach as test_assign_story_id).
"""
import datetime
import os
import sys
import types

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (HERE, os.path.join(HERE, "jobs")):
    if p not in sys.path:
        sys.path.insert(0, p)

import classify_pending  # noqa: E402
from classify_pending import (  # noqa: E402
    _classifier_version, _ensure_journalist, _reclassify_nollm, NOLLM_SUFFIX,
)


# --- _classifier_version (BUG-019) -----------------------------------------

def test_classifier_version_plain_when_llm_present():
    assert _classifier_version(7, {7: {}}, "v1") == "v1"


def test_classifier_version_tagged_when_llm_missing():
    assert _classifier_version(7, {}, "v1") == "v1" + NOLLM_SUFFIX
    assert _classifier_version(7, {9: {}}, "v2") == "v2-nollm"


# --- _ensure_journalist first_seen seeding (BUG-017) -----------------------

class _JCursor:
    def __init__(self, existing_row=None, lastrowid=42):
        self._row = existing_row
        self.lastrowid = lastrowid
        self.calls = []     # (op, params)
        self.sql_log = []

    def execute(self, sql, params=()):
        op = sql.strip().split()[0].upper()
        self.calls.append((op, params))
        self.sql_log.append(sql)
        self._last = self._row if op == "SELECT" else None

    def fetchone(self):
        return self._last


PUB = datetime.datetime(2025, 1, 2, 3, 4, 5)


def test_ensure_journalist_new_inserts_with_published_at():
    cur = _JCursor(existing_row=None, lastrowid=99)
    jid = _ensure_journalist(cur, "jane doe", "Jane Doe", PUB)
    assert jid == 99
    ops = [op for op, _ in cur.calls]
    assert ops == ["SELECT", "INSERT"]
    insert_sql, insert_params = cur.sql_log[1], cur.calls[1][1]
    assert "first_seen_at" in insert_sql
    assert insert_params == ("jane doe", "Jane Doe", PUB)


def test_ensure_journalist_new_without_published_at_uses_two_col_insert():
    cur = _JCursor(existing_row=None, lastrowid=5)
    jid = _ensure_journalist(cur, "jane doe", "Jane Doe", None)
    assert jid == 5
    assert cur.calls[1][1] == ("jane doe", "Jane Doe")
    assert "first_seen_at" not in cur.sql_log[1]


def test_ensure_journalist_existing_pulls_first_seen_earlier():
    cur = _JCursor(existing_row={"id": 12})
    jid = _ensure_journalist(cur, "jane doe", "Jane Doe", PUB)
    assert jid == 12
    ops = [op for op, _ in cur.calls]
    assert ops == ["SELECT", "UPDATE"]
    # UPDATE only lowers first_seen_at (WHERE first_seen_at > new value).
    assert cur.calls[1][1] == (PUB, 12, PUB)
    assert "first_seen_at > %s" in cur.sql_log[1]


def test_ensure_journalist_existing_no_published_at_is_noop_update():
    cur = _JCursor(existing_row={"id": 12})
    jid = _ensure_journalist(cur, "jane doe", "Jane Doe", None)
    assert jid == 12
    assert [op for op, _ in cur.calls] == ["SELECT"]  # no UPDATE issued


# --- _reclassify_nollm bounded pass (BUG-019) ------------------------------

class _RCursor:
    def __init__(self, select_rows):
        self._select_rows = select_rows
        self.executed = []  # (op, sql, params)

    def execute(self, sql, params=()):
        op = sql.strip().split()[0].upper()
        self.executed.append((op, sql, params))
        self._is_select = op == "SELECT"

    def fetchall(self):
        return self._select_rows if self._is_select else []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _RConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.pings = 0
        self.commits = 0

    def cursor(self):
        return self._cursor

    def ping(self, reconnect=False):
        self.pings += 1

    def commit(self):
        self.commits += 1


def _cfg(**kw):
    base = dict(CLASSIFIER_VERSION="v1", LLM_BATCH_SIZE=10,
                ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="m")
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_reclassify_respects_budget_deadline():
    cur = _RCursor([])
    conn = _RConn(cur)
    n, cost = _reclassify_nollm(conn, _cfg(), deadline=0)  # already past
    assert (n, cost) == (0, 0.0)
    assert cur.executed == []


def test_reclassify_noop_when_no_tagged_rows():
    cur = _RCursor([])  # SELECT returns nothing
    conn = _RConn(cur)
    n, cost = _reclassify_nollm(conn, _cfg(), deadline=time_future())
    assert (n, cost) == (0, 0.0)
    # only the SELECT ran; nothing committed
    assert [e[0] for e in cur.executed] == ["SELECT"]
    assert conn.commits == 0


def test_reclassify_updates_rows_and_clears_marker(monkeypatch):
    rows = [
        {"id": 1, "title": "t1", "summary": "s1", "source_name": "S", "source_lean": 0.1},
        {"id": 2, "title": "t2", "summary": "s2", "source_name": "S", "source_lean": -0.2},
    ]
    cur = _RCursor(rows)
    conn = _RConn(cur)

    def _perception(**overrides):
        base = {"tone_calmness": 0.6, "sensationalism": 0.2,
                "analysis_depth": 0.5, "emotional_charge": 0.3,
                "hedging": 0.4, "solution_orientation": 0.5}
        base.update(overrides)
        return base

    def fake_llm(api_key, model, items):
        assert [it[0] for it in items] == [1, 2]
        return {
            "by_id": {
                1: {"political_lean": 0.3, "objectivity": 0.7, **_perception()},
                2: {"political_lean": -0.5, "objectivity": 0.4,
                    **_perception(tone_calmness=0.1, sensationalism=0.9)},
            },
            "usage": {"model": model, "input_tokens": 10, "output_tokens": 5,
                      "cache_read_tokens": 0, "est_cost_usd": 0.002},
        }

    monkeypatch.setattr(classify_pending, "classify_batch_llm", fake_llm)
    n, cost = _reclassify_nollm(conn, _cfg(), deadline=time_future())
    assert n == 2
    assert cost == 0.002
    ops = [e[0] for e in cur.executed]
    # 1 SELECT + 2 UPDATEs + 1 llm_usage INSERT
    assert ops == ["SELECT", "UPDATE", "UPDATE", "INSERT"]
    # UPDATEs rewrite classifier_version back to the clean base version and
    # now also carry the 6 perception fields + 3 geo columns. The fake_llm
    # above omits primary_location, so geo_lat/geo_lng/geo_place stay None.
    up1 = cur.executed[1][2]
    assert up1 == (0.3, 0.7, 0.6, 0.2, 0.5, 0.3, 0.4, 0.5, None, None, None, "v1", 1)
    up2 = cur.executed[2][2]
    assert up2[:2] == (-0.5, 0.4)
    assert up2[2] == 0.1   # tone_calmness override
    assert up2[3] == 0.9   # sensationalism override
    assert up2[-5:] == (None, None, None, "v1", 2)
    assert conn.commits == 1


def test_reclassify_leaves_rows_tagged_when_llm_unavailable(monkeypatch):
    rows = [{"id": 1, "title": "t", "summary": "s",
             "source_name": "S", "source_lean": 0.0}]
    cur = _RCursor(rows)
    conn = _RConn(cur)

    def boom(*a, **k):
        raise classify_pending.LLMUnavailable("still down")

    monkeypatch.setattr(classify_pending, "classify_batch_llm", boom)
    n, cost = _reclassify_nollm(conn, _cfg(), deadline=time_future())
    assert (n, cost) == (0, 0.0)
    # SELECT ran, but no UPDATE/commit — rows stay tagged for the next tick.
    assert [e[0] for e in cur.executed] == ["SELECT"]
    assert conn.commits == 0


def time_future():
    import time
    return time.time() + 3600
