"""Unit tests for `_assign_story_id` in jobs/classify_pending.py.

Uses a fake cursor that records `execute()` calls and returns scripted
`fetchone()` results in sequence. The function makes up to 3 queries in
order: (1) title_hash lookup, (2) simhash lookup if 1 misses, (3) canonical
lookup if a candidate was found.
"""
import datetime
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (HERE, os.path.join(HERE, "jobs")):
    if p not in sys.path:
        sys.path.insert(0, p)

from classify_pending import _assign_story_id  # noqa: E402


class FakeCursor:
    def __init__(self, scripted_fetchone):
        self._fetch_queue = list(scripted_fetchone)
        self.calls = []     # list of (op, params) — stable 2-tuple contract
        self.sql_log = []   # full SQL strings, parallel to self.calls

    def execute(self, sql, params=()):
        self.calls.append((sql.strip().split()[0].upper(), params))
        self.sql_log.append(sql)
        # SELECTs consume a fetch result; UPDATEs do not.
        op = sql.strip().split()[0].upper()
        if op == "SELECT":
            self._next = self._fetch_queue.pop(0) if self._fetch_queue else None
        else:
            self._next = None

    def fetchone(self):
        return self._next


def _art(id_=10, title_hash="abc", simhash=0x1234, rep=0.7, pub=None):
    return {
        "id": id_,
        "title_hash": title_hash,
        "simhash": simhash,
        "source_reputation": rep,
        "published_at": pub or datetime.datetime(2026, 5, 13, 10, 0, 0),
    }


def test_no_match_returns_false_and_no_updates():
    # SELECT title_hash -> None; SELECT simhash -> None.
    cur = FakeCursor(scripted_fetchone=[None, None])
    out = _assign_story_id(cur, _art())
    assert out is False
    ops = [op for op, _ in cur.calls]
    assert ops == ["SELECT", "SELECT"]


def test_title_hash_match_adopts_existing_canonical_when_we_have_lower_rep():
    # candidate found via title_hash, story_id=5; canonical (id=5) has rep 0.9 > us 0.7
    cur = FakeCursor(scripted_fetchone=[
        {"id": 5, "story_id": 5},  # title_hash lookup hit
        {"id": 5, "published_at": datetime.datetime(2026, 5, 13, 9, 0, 0),
         "source_reputation": 0.9},  # canonical lookup
    ])
    out = _assign_story_id(cur, _art(id_=10, rep=0.7))
    assert out is True
    ops = [op for op, _ in cur.calls]
    # SELECT title_hash, SELECT canonical, UPDATE (adopt)
    assert ops == ["SELECT", "SELECT", "UPDATE"]
    # Should set our row's story_id to canonical id (5).
    update_params = cur.calls[2][1]
    assert update_params == (5, 10)


def test_title_hash_match_promotes_self_when_higher_rep():
    cur = FakeCursor(scripted_fetchone=[
        {"id": 5, "story_id": 5},  # title_hash hit; existing story_id=5
        {"id": 5, "published_at": datetime.datetime(2026, 5, 13, 9, 0, 0),
         "source_reputation": 0.4},  # canonical has lower rep than us
    ])
    out = _assign_story_id(cur, _art(id_=10, rep=0.9))
    assert out is True
    ops = [op for op, _ in cur.calls]
    assert ops == ["SELECT", "SELECT", "UPDATE"]
    # Promote: rewrite all members of story_id=5 to point at 10.
    update_params = cur.calls[2][1]
    assert update_params == (10, 5)


def test_simhash_match_when_title_hash_misses():
    cur = FakeCursor(scripted_fetchone=[
        None,                                       # title_hash miss
        {"id": 8, "story_id": 8, "hd": 2},          # simhash hit
        {"id": 8, "published_at": datetime.datetime(2026, 5, 13, 8, 0, 0),
         "source_reputation": 0.8},                 # canonical
    ])
    out = _assign_story_id(cur, _art(id_=10, rep=0.5))
    assert out is True
    ops = [op for op, _ in cur.calls]
    assert ops == ["SELECT", "SELECT", "SELECT", "UPDATE"]
    # We have lower rep, so we adopt canonical id=8.
    assert cur.calls[3][1] == (8, 10)


def test_title_hash_tiebreak_older_published_wins_canonical():
    # Equal rep, our published_at is earlier than canonical's -> promote us.
    older = datetime.datetime(2026, 5, 13, 5, 0, 0)
    newer = datetime.datetime(2026, 5, 13, 10, 0, 0)
    cur = FakeCursor(scripted_fetchone=[
        {"id": 5, "story_id": 5},
        {"id": 5, "published_at": newer, "source_reputation": 0.7},
    ])
    out = _assign_story_id(cur, _art(id_=10, rep=0.7, pub=older))
    assert out is True
    assert cur.calls[-1][0] == "UPDATE"
    # Promote (we're older + equal rep)
    assert cur.calls[-1][1] == (10, 5)


def test_missing_canonical_falls_back_to_candidate_id():
    # Title_hash hit returns story_id=5, but the canonical row (id=5) is gone.
    cur = FakeCursor(scripted_fetchone=[
        {"id": 7, "story_id": 5},  # candidate row id=7 in cluster 5
        None,                       # canonical lookup misses
    ])
    out = _assign_story_id(cur, _art(id_=10))
    assert out is True
    # Should UPDATE our row's story_id to candidate's id (7), not 5.
    assert cur.calls[-1][0] == "UPDATE"
    assert cur.calls[-1][1] == (7, 10)


def test_null_simhash_and_null_title_hash_no_op():
    cur = FakeCursor(scripted_fetchone=[])
    art = {"id": 10, "title_hash": None, "simhash": None,
           "source_reputation": 0.5, "published_at": None}
    out = _assign_story_id(cur, art)
    assert out is False
    assert cur.calls == []


def test_zero_simhash_does_not_cluster(monkeypatch):
    # simhash==0 means "no usable tokens"; it must NOT run the simhash branch
    # (otherwise every zero-simhash article is Hamming-0 from every other and
    # collapses into one bogus megacluster — BUG-018).
    cur = FakeCursor(scripted_fetchone=[])
    art = {"id": 10, "title_hash": None, "simhash": 0,
           "source_reputation": 0.5,
           "published_at": datetime.datetime(2026, 5, 17, 9, 0, 0)}
    out = _assign_story_id(cur, art)
    assert out is False
    # No simhash SELECT issued at all.
    assert cur.calls == []


def test_zero_simhash_still_uses_title_hash():
    # A zero simhash must not break the title_hash clustering path.
    cur = FakeCursor(scripted_fetchone=[
        {"id": 5, "story_id": 5},                       # title_hash hit
        {"id": 5, "published_at": datetime.datetime(2026, 5, 17, 8, 0, 0),
         "source_reputation": 0.9},                     # canonical
    ])
    out = _assign_story_id(cur, _art(id_=10, title_hash="abc", simhash=0, rep=0.7))
    assert out is True
    ops = [op for op, _ in cur.calls]
    # title SELECT, canonical SELECT, UPDATE — no simhash SELECT.
    assert ops == ["SELECT", "SELECT", "UPDATE"]
    assert cur.calls[2][1] == (5, 10)


def test_simhash_query_excludes_zero_rows():
    # When we DO run the simhash branch, the SQL must exclude a2.simhash=0
    # candidates so a real article can't match the zero-bucket.
    cur = FakeCursor(scripted_fetchone=[None, None])  # title miss, simhash miss
    _assign_story_id(cur, _art(id_=10, title_hash="abc", simhash=0x1234))
    # The simhash candidate query is the one that references BIT_COUNT.
    sim_sql = [s for s in cur.sql_log if "BIT_COUNT" in s]
    assert len(sim_sql) == 1
    assert "a2.simhash <> 0" in sim_sql[0]
