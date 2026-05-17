"""Pure tests for app.spectrum (no Flask / no DB — runs in any env)."""
import datetime as dt

from app.spectrum import lean_bucket, pick_spectrum_sample


def _m(id_, *, source_id=None, lean=0.0, pub=None):
    return {
        "id": id_,
        "source_id": source_id if source_id is not None else id_,
        "political_lean": lean,
        "published_at": pub or dt.datetime(2026, 5, 13, 12, 0, 0),
    }


def test_lean_bucket_thresholds():
    assert lean_bucket(-0.9) == "left"
    assert lean_bucket(-0.2) == "left"      # boundary inclusive
    assert lean_bucket(-0.19) == "center"
    assert lean_bucket(0.0) == "center"
    assert lean_bucket(0.2) == "right"      # boundary inclusive
    assert lean_bucket(0.9) == "right"


def test_lean_bucket_none_is_center():
    assert lean_bucket(None) == "center"


def test_excludes_the_card_article():
    members = [_m(100, lean=-0.5), _m(101, lean=0.5), _m(102, lean=0.0)]
    out = pick_spectrum_sample(members, exclude_id=100, limit=3)
    ids = [m["id"] for m in out]
    assert 100 not in ids
    assert set(ids) == {101, 102}


def test_dedupes_by_source_keeps_one_per_outlet():
    members = [
        _m(100, source_id=1, lean=-0.5),               # canonical (excluded)
        _m(101, source_id=2, lean=0.5, pub=dt.datetime(2026, 5, 13, 9, 0)),
        _m(102, source_id=2, lean=0.5, pub=dt.datetime(2026, 5, 13, 15, 0)),
        _m(103, source_id=3, lean=0.0),
    ]
    out = pick_spectrum_sample(members, exclude_id=100, limit=3)
    src = [m["source_id"] for m in out]
    assert src.count(2) == 1
    # newest from source 2 wins
    assert 102 in [m["id"] for m in out]
    assert 101 not in [m["id"] for m in out]


def test_spans_the_spectrum_when_one_side_dominates():
    members = [_m(1, lean=-0.4)]  # canonical excluded
    members += [_m(i, source_id=i, lean=-0.6) for i in range(10, 18)]  # 8 left
    members += [_m(50, source_id=50, lean=0.0)]   # 1 center
    members += [_m(60, source_id=60, lean=0.6)]   # 1 right
    out = pick_spectrum_sample(members, exclude_id=1, limit=3)
    buckets = {lean_bucket(m["political_lean"]) for m in out}
    assert buckets == {"left", "center", "right"}


def test_limit_is_respected():
    members = [_m(1, lean=0.0)] + [_m(i, source_id=i, lean=0.0) for i in range(10, 30)]
    out = pick_spectrum_sample(members, exclude_id=1, limit=3)
    assert len(out) == 3


def test_returns_fewer_than_limit_when_few_sources():
    members = [_m(1, source_id=1, lean=0.0), _m(2, source_id=2, lean=0.3)]
    out = pick_spectrum_sample(members, exclude_id=1, limit=3)
    assert [m["id"] for m in out] == [2]


def test_all_same_source_yields_single_entry():
    members = [
        _m(1, source_id=7, lean=0.0),
        _m(2, source_id=7, lean=0.0),
        _m(3, source_id=7, lean=0.0),
    ]
    out = pick_spectrum_sample(members, exclude_id=1, limit=3)
    assert len(out) == 1
    assert out[0]["source_id"] == 7


def test_none_published_at_does_not_crash_and_is_oldest():
    members = [
        _m(1, source_id=1, lean=0.0),
        _m(2, source_id=2, lean=0.0, pub=None),
        _m(3, source_id=3, lean=0.0, pub=dt.datetime(2026, 5, 13, 18, 0)),
    ]
    members[1]["published_at"] = None
    out = pick_spectrum_sample(members, exclude_id=1, limit=2)
    # both center, same source-dedup not triggered; newest (id 3) first
    assert [m["id"] for m in out] == [3, 2]


def test_deterministic_across_runs():
    members = [_m(1, lean=0.0)] + [
        _m(i, source_id=i, lean=(-0.5 if i % 2 else 0.5),
           pub=dt.datetime(2026, 5, 13, 10 + i % 5, 0))
        for i in range(10, 25)
    ]
    a = [m["id"] for m in pick_spectrum_sample(members, exclude_id=1, limit=3)]
    b = [m["id"] for m in pick_spectrum_sample(members, exclude_id=1, limit=3)]
    assert a == b
