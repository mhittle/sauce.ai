"""Pure-helper tests for breaking-news alert detection.

No Haiku / DB / SMTP / browser involved — the cron job
(``jobs/breaking_alerts.py``) does the orchestration; these tests pin
the decision boundaries so future edits to the cron can't silently
weaken the candidate threshold, the mute-suppression check, the
daily-cap guard, or the LLM-verdict clamp.
"""
import os
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from app import breaking


# --- select_candidates ---------------------------------------------------

def test_select_candidates_keeps_rows_at_or_above_threshold():
    rows = [
        {"story_id": 1, "outlet_count": 15},
        {"story_id": 2, "outlet_count": 12},  # equal to threshold → kept
        {"story_id": 3, "outlet_count": 11},  # below threshold → dropped
        {"story_id": 4, "outlet_count": 30},
    ]
    out = breaking.select_candidates(rows, min_outlets=12)
    assert [r["story_id"] for r in out] == [1, 2, 4]


def test_select_candidates_preserves_input_order():
    rows = [{"story_id": i, "outlet_count": 20} for i in (5, 3, 9, 1)]
    out = breaking.select_candidates(rows, min_outlets=10)
    assert [r["story_id"] for r in out] == [5, 3, 9, 1]


def test_select_candidates_drops_non_numeric_outlet_count():
    rows = [
        {"story_id": 1, "outlet_count": None},
        {"story_id": 2, "outlet_count": "bad"},
        {"story_id": 3, "outlet_count": 14},
    ]
    out = breaking.select_candidates(rows, min_outlets=12)
    assert [r["story_id"] for r in out] == [3]


def test_select_candidates_empty_input():
    assert breaking.select_candidates([], min_outlets=12) == []


# --- is_suppressed -------------------------------------------------------

def test_is_suppressed_matches_case_insensitive_substring():
    assert breaking.is_suppressed("Royal wedding photos leaked", ["royal"]) is True
    assert breaking.is_suppressed("ROYAL family on tour", ["royal"]) is True


def test_is_suppressed_no_match_returns_false():
    assert breaking.is_suppressed("Earthquake hits Tokyo", ["royal", "crypto"]) is False


def test_is_suppressed_handles_empty_input():
    assert breaking.is_suppressed("", ["royal"]) is False
    assert breaking.is_suppressed("Anything", []) is False
    assert breaking.is_suppressed(None, ["royal"]) is False


def test_is_suppressed_skips_empty_terms():
    # An empty/whitespace term must not match every event (substring of "" is everywhere).
    assert breaking.is_suppressed("Important event", ["", None]) is False


# --- daily_cap_ok --------------------------------------------------------

def test_daily_cap_ok_clean_slate_when_no_row():
    today = date(2026, 5, 22)
    assert breaking.daily_cap_ok(None, max_per_day=3, today=today) is True


def test_daily_cap_ok_under_cap_today_returns_true():
    today = date(2026, 5, 22)
    row = {"alerts_day": today, "alerts_today": 2}
    assert breaking.daily_cap_ok(row, max_per_day=3, today=today) is True


def test_daily_cap_ok_at_cap_today_returns_false():
    today = date(2026, 5, 22)
    row = {"alerts_day": today, "alerts_today": 3}
    assert breaking.daily_cap_ok(row, max_per_day=3, today=today) is False


def test_daily_cap_ok_yesterday_resets():
    today = date(2026, 5, 22)
    yesterday = today - timedelta(days=1)
    row = {"alerts_day": yesterday, "alerts_today": 99}
    assert breaking.daily_cap_ok(row, max_per_day=3, today=today) is True


def test_daily_cap_ok_null_day_is_clean_slate():
    today = date(2026, 5, 22)
    row = {"alerts_day": None, "alerts_today": 0}
    assert breaking.daily_cap_ok(row, max_per_day=3, today=today) is True


def test_daily_cap_ok_zero_max_disables_sending():
    today = date(2026, 5, 22)
    row = {"alerts_day": today, "alerts_today": 0}
    assert breaking.daily_cap_ok(row, max_per_day=0, today=today) is False


# --- parse_llm_verdict ---------------------------------------------------

def test_parse_llm_verdict_strict_json():
    text = '{"is_major": true, "headline": "X happened", "blurb": "Details."}'
    v = breaking.parse_llm_verdict(text)
    assert v == {"is_major": True, "headline": "X happened", "blurb": "Details."}


def test_parse_llm_verdict_strips_json_fence():
    text = '```json\n{"is_major": false, "headline": "no", "blurb": ""}\n```'
    v = breaking.parse_llm_verdict(text)
    assert v == {"is_major": False, "headline": "no", "blurb": ""}


def test_parse_llm_verdict_clamps_long_strings():
    big_head = "A" * 500
    big_blurb = "B" * 1000
    import json as _json
    text = _json.dumps({"is_major": True, "headline": big_head, "blurb": big_blurb})
    v = breaking.parse_llm_verdict(text)
    assert v["is_major"] is True
    assert len(v["headline"]) == 200
    assert len(v["blurb"]) == 500


def test_parse_llm_verdict_malformed_json_returns_none():
    assert breaking.parse_llm_verdict("not json") is None
    assert breaking.parse_llm_verdict("") is None
    assert breaking.parse_llm_verdict(None) is None


def test_parse_llm_verdict_non_object_payload_returns_none():
    # JSON list / scalar / null → no usable verdict.
    assert breaking.parse_llm_verdict("[1,2,3]") is None
    assert breaking.parse_llm_verdict("true") is None
    assert breaking.parse_llm_verdict("null") is None


def test_parse_llm_verdict_missing_fields_default_safely():
    v = breaking.parse_llm_verdict('{"is_major": false}')
    assert v == {"is_major": False, "headline": "", "blurb": ""}


def test_parse_llm_verdict_is_major_coerces_to_bool():
    # is_major: 1/0 from a sloppy model still yields a real bool.
    v_true = breaking.parse_llm_verdict('{"is_major": 1, "headline": "h", "blurb": "b"}')
    v_false = breaking.parse_llm_verdict('{"is_major": 0, "headline": "", "blurb": ""}')
    assert v_true["is_major"] is True
    assert v_false["is_major"] is False
