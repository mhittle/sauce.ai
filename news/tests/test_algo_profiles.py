"""Unit tests for the pure profile helpers in `app.profiles`.

These are Flask-free and DB-free (same convention as test_discovery /
test_simhash) so they run in the sandbox without pymysql. The route
wiring in app/routes/algo.py is exercised by the maintainer/CI in a
real env.
"""
from app.profiles import (
    MAX_NAME_LEN,
    clean_profile_name,
    next_default_name,
    pick_promotion,
)


def test_clean_profile_name_trims_and_keeps():
    assert clean_profile_name("  Morning brief  ") == "Morning brief"


def test_clean_profile_name_empty_falls_back():
    assert clean_profile_name("") == "Custom"
    assert clean_profile_name(None) == "Custom"
    assert clean_profile_name("   ") == "Custom"


def test_clean_profile_name_custom_fallback():
    assert clean_profile_name("", fallback="Custom 3") == "Custom 3"


def test_clean_profile_name_caps_length():
    long = "x" * 500
    assert len(clean_profile_name(long)) == MAX_NAME_LEN


def test_next_default_name_first_is_base():
    assert next_default_name([]) == "Custom"
    assert next_default_name(["Morning brief", "Weekend"]) == "Custom"


def test_next_default_name_increments():
    assert next_default_name(["Custom"]) == "Custom 2"
    assert next_default_name(["Custom", "Custom 2"]) == "Custom 3"


def test_next_default_name_is_case_and_space_insensitive():
    assert next_default_name(["  custom  ", "CUSTOM 2"]) == "Custom 3"


def test_next_default_name_skips_gaps():
    # "Custom 2" taken but "Custom" free -> base is returned first
    assert next_default_name(["Custom 2"]) == "Custom"
    # base + "Custom 2" taken, "Custom 3" free
    assert next_default_name(["Custom", "Custom 2"]) == "Custom 3"


def test_next_default_name_handles_none_entries():
    assert next_default_name([None, "Custom"]) == "Custom 2"


def test_pick_promotion_returns_first_other():
    rows = [{"id": 5}, {"id": 9}, {"id": 2}]
    assert pick_promotion(rows, deleted_id=5) == 9


def test_pick_promotion_skips_deleted_anywhere():
    rows = [{"id": 9}, {"id": 5}, {"id": 2}]
    assert pick_promotion(rows, deleted_id=5) == 9


def test_pick_promotion_none_when_empty():
    assert pick_promotion([], deleted_id=5) is None
    assert pick_promotion([{"id": 5}], deleted_id=5) is None
