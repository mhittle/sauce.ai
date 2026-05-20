"""Pure tests for the lab-landing voting helpers.

No Flask / no DB — same convention as test_gallery / test_term_prefs.
"""
from app.lab_concepts import (
    LAB_CONCEPT_KEYS,
    VOTE_DOWN,
    VOTE_NONE,
    VOTE_UP,
    is_valid_concept,
    is_valid_voter_token,
    normalize_vote,
    tally_with_you,
)


def test_concept_keys_includes_first_wave():
    for k in ("recipes", "travel", "money", "fit", "learn", "inbox", "stage"):
        assert k in LAB_CONCEPT_KEYS


def test_concept_keys_includes_radical_wave():
    for k in ("jar", "negotiate", "clone", "doctor", "legal",
              "tax", "estate", "decide", "friend", "mirror"):
        assert k in LAB_CONCEPT_KEYS


def test_news_is_not_a_votable_concept():
    # `news` is already live and should not accept votes.
    assert "news" not in LAB_CONCEPT_KEYS


def test_is_valid_concept_rejects_unknown():
    assert is_valid_concept("jar") is True
    assert is_valid_concept("unknown") is False
    assert is_valid_concept("") is False
    assert is_valid_concept(None) is False
    assert is_valid_concept(123) is False


def test_normalize_vote_int_forms():
    assert normalize_vote(1) == VOTE_UP
    assert normalize_vote(-1) == VOTE_DOWN
    assert normalize_vote(0) == VOTE_NONE
    assert normalize_vote(5) == VOTE_UP
    assert normalize_vote(-99) == VOTE_DOWN


def test_normalize_vote_string_forms():
    for s in ("up", "UP", "+1", "1", "upvote"):
        assert normalize_vote(s) == VOTE_UP, s
    for s in ("down", "Down", "-1", "downvote"):
        assert normalize_vote(s) == VOTE_DOWN, s
    for s in ("", "0", "garbage", "  "):
        assert normalize_vote(s) == VOTE_NONE, s


def test_normalize_vote_rejects_bool_and_none():
    assert normalize_vote(True) == VOTE_NONE
    assert normalize_vote(False) == VOTE_NONE
    assert normalize_vote(None) == VOTE_NONE


def test_voter_token_validation():
    assert is_valid_voter_token("a" * 40) is True
    assert is_valid_voter_token("0123456789abcdef" * 2 + "01234567") is True
    # wrong length
    assert is_valid_voter_token("a" * 39) is False
    assert is_valid_voter_token("a" * 41) is False
    # uppercase hex not accepted (we mint lowercase)
    assert is_valid_voter_token("A" * 40) is False
    # non-hex
    assert is_valid_voter_token("g" * 40) is False
    # wrong type
    assert is_valid_voter_token(None) is False
    assert is_valid_voter_token(123) is False


def test_tally_with_you_counts_ups_and_downs():
    rows = [(1,), (1,), (-1,), (1,), (-1,)]
    t = tally_with_you(rows, your_vote=1)
    assert t == {"up": 3, "down": 2, "score": 1, "you": 1}


def test_tally_with_you_empty():
    assert tally_with_you([], your_vote=0) == {"up": 0, "down": 0, "score": 0, "you": 0}


def test_tally_with_you_handles_dict_rows():
    rows = [{"vote": 1}, {"vote": -1}, {"vote": 1}]
    t = tally_with_you(rows, your_vote=-1)
    assert t == {"up": 2, "down": 1, "score": 1, "you": -1}


def test_tally_with_you_zero_votes_ignored():
    rows = [(1,), (0,), (-1,), (0,)]
    t = tally_with_you(rows, your_vote=0)
    assert t == {"up": 1, "down": 1, "score": 0, "you": 0}
