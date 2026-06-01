"""Pure tests for `app.blindspot`.

No Flask / DB / Haiku — pins the classification + labeling boundaries so
the route in `app/routes/blindspot.py` can rely on stable semantics.
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from app.blindspot import (
    REASON_FILTERED, REASON_LOW_RELEVANCE, REASON_MUTED,
    classify_blindspots, reason_label,
)


def _big(sid, n):
    return {"story_id": sid, "outlet_count": n}


# --- shown_story_ids excludes -------------------------------------------

def test_story_in_shown_set_is_not_a_blindspot():
    out = classify_blindspots([_big(1, 9), _big(2, 8)], shown_story_ids=[1])
    assert [r["story_id"] for r in out] == [2]


def test_story_absent_from_shown_set_is_a_blindspot():
    out = classify_blindspots([_big(7, 5)], shown_story_ids=[1, 2])
    assert len(out) == 1
    assert out[0]["story_id"] == 7
    assert out[0]["outlet_count"] == 5


def test_empty_inputs_return_empty():
    assert classify_blindspots([], []) == []
    assert classify_blindspots(None, None) == []


# --- ordering ------------------------------------------------------------

def test_ordered_by_outlet_count_desc():
    big = [_big(10, 5), _big(20, 15), _big(30, 9)]
    out = classify_blindspots(big, shown_story_ids=[])
    assert [r["story_id"] for r in out] == [20, 30, 10]


def test_ties_broken_by_story_id_ascending():
    big = [_big(3, 10), _big(1, 10), _big(2, 10)]
    out = classify_blindspots(big, shown_story_ids=[])
    assert [r["story_id"] for r in out] == [1, 2, 3]


# --- priority: mute > filter > low_relevance ----------------------------

def test_low_relevance_when_no_mute_no_filter():
    out = classify_blindspots([_big(1, 5)], shown_story_ids=[])
    assert out[0]["hidden_reason"] == REASON_LOW_RELEVANCE
    assert out[0]["mute_term"] is None


def test_filter_label_when_in_filter_hits():
    out = classify_blindspots(
        [_big(1, 5)], shown_story_ids=[], filter_hits=[1]
    )
    assert out[0]["hidden_reason"] == REASON_FILTERED


def test_mute_label_when_in_mute_hits():
    out = classify_blindspots(
        [_big(1, 5)], shown_story_ids=[],
        mute_hits={1: "crypto"}, filter_hits=[1],
    )
    assert out[0]["hidden_reason"] == REASON_MUTED
    assert out[0]["mute_term"] == "crypto"


def test_mute_beats_filter_beats_low_relevance():
    """Same story flagged as both muted AND filtered → mute wins."""
    out = classify_blindspots(
        [_big(1, 5), _big(2, 4), _big(3, 3)],
        shown_story_ids=[],
        mute_hits={1: "crypto"},
        filter_hits=[2],
    )
    by_id = {r["story_id"]: r for r in out}
    assert by_id[1]["hidden_reason"] == REASON_MUTED
    assert by_id[2]["hidden_reason"] == REASON_FILTERED
    assert by_id[3]["hidden_reason"] == REASON_LOW_RELEVANCE


# --- max_items cap -------------------------------------------------------

def test_max_items_caps_output():
    big = [_big(i, 100 - i) for i in range(1, 21)]  # 20 candidates
    out = classify_blindspots(big, shown_story_ids=[], max_items=5)
    assert len(out) == 5
    assert [r["story_id"] for r in out] == [1, 2, 3, 4, 5]


def test_max_items_zero_returns_empty():
    assert classify_blindspots([_big(1, 5)], shown_story_ids=[], max_items=0) == []


def test_max_items_negative_returns_empty():
    assert classify_blindspots([_big(1, 5)], shown_story_ids=[], max_items=-3) == []


# --- input sanitation ----------------------------------------------------

def test_rows_without_story_id_dropped_silently():
    big = [{"story_id": None, "outlet_count": 99}, _big(2, 3)]
    out = classify_blindspots(big, shown_story_ids=[])
    assert [r["story_id"] for r in out] == [2]


def test_rows_with_bad_outlet_count_dropped_silently():
    big = [
        {"story_id": 1, "outlet_count": None},
        {"story_id": 2, "outlet_count": "bad"},
        _big(3, 7),
    ]
    out = classify_blindspots(big, shown_story_ids=[])
    assert [r["story_id"] for r in out] == [3]


def test_shown_set_coerces_non_int_ids_safely():
    """Passing a None or non-int into shown_story_ids must not raise; it
    just doesn't exclude anything."""
    out = classify_blindspots([_big(1, 5)], shown_story_ids=[None, "bad", 1])
    assert out == []  # 1 still excluded via the valid entry


def test_mute_hits_with_non_int_keys_ignored():
    out = classify_blindspots(
        [_big(1, 5)],
        shown_story_ids=[],
        mute_hits={None: "x", "nope": "y", 1: "crypto"},
    )
    assert out[0]["hidden_reason"] == REASON_MUTED
    assert out[0]["mute_term"] == "crypto"


def test_filter_hits_with_non_int_ids_ignored():
    out = classify_blindspots(
        [_big(1, 5)],
        shown_story_ids=[],
        filter_hits=[None, "bad", 1],
    )
    assert out[0]["hidden_reason"] == REASON_FILTERED


# --- reason_label --------------------------------------------------------

def test_reason_label_muted_with_term_quotes_term():
    assert "crypto" in reason_label(REASON_MUTED, term="crypto")


def test_reason_label_muted_without_term_falls_back():
    assert reason_label(REASON_MUTED) == "Muted by your keyword"


def test_reason_label_filtered():
    assert "filter" in reason_label(REASON_FILTERED).lower()


def test_reason_label_low_relevance():
    assert "relevance" in reason_label(REASON_LOW_RELEVANCE).lower()


def test_reason_label_unknown_falls_back_to_low_relevance():
    assert reason_label("bogus") == reason_label(REASON_LOW_RELEVANCE)
