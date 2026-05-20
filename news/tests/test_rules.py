from app.classifier.rules import (
    flesch_kincaid_grade, normalized_reading_level, info_density,
    normalize_byline, split_bylines, compute_rules_features,
    normalize_title, title_hash,
    source_obscurity_score, story_obscurity_score, popularity_score,
    headline_length_score, caps_ratio_score, punctuation_intensity_score,
    numeric_density_score, question_headline_score, quote_present_score,
)


def test_flesch_basic():
    grade = flesch_kincaid_grade("The cat sat on the mat. It was a sunny day.")
    assert grade >= 0
    assert grade < 12  # short simple sentences


def test_flesch_handles_empty():
    assert flesch_kincaid_grade("") == 0.0
    assert normalized_reading_level("") == 0.0


def test_info_density_range():
    text = "President Joe Biden met with 12 leaders in Brussels on March 24, 2024."
    d = info_density(text)
    assert 0.0 <= d <= 1.0
    assert d > info_density("the the the the the")


def test_normalize_byline():
    assert normalize_byline("By Jane Smith") == "jane smith"
    assert normalize_byline("  By   Jane  Smith  ") == "jane smith"
    assert normalize_byline("") == ""


def test_split_bylines():
    out = split_bylines("By Jane Smith, John Doe and Reuters Staff")
    assert "jane smith" in out
    assert "john doe" in out
    assert "reuters staff" in out


def test_compute_rules_features_shape():
    art = {"title": "Breaking: market jumps", "summary": "Stocks rose 2% on news from Washington."}
    src = {"source_lean": -0.3, "source_reputation": 0.8, "category": "business", "country": "US", "region": "national"}
    feats = compute_rules_features(art, src)
    assert "reading_level" in feats and 0 <= feats["reading_level"] <= 1
    assert "info_density" in feats and 0 <= feats["info_density"] <= 1
    assert feats["source_lean"] == -0.3
    assert feats["category"] == "business"


def test_normalize_title_strips_punctuation_and_case():
    assert normalize_title("Hello, World!") == "hello world"
    assert normalize_title("  Multiple   spaces  ") == "multiple spaces"
    assert normalize_title("") == ""


def test_title_hash_stable_across_punctuation():
    a = title_hash("Big bank profits surge in Q2")
    b = title_hash("Big bank profits surge in Q2!")
    c = title_hash("BIG bank   profits  surge in Q2")
    assert a == b == c
    assert len(a) == 40  # sha1 hex


def test_source_obscurity_endpoints():
    assert source_obscurity_score(0) == 1.0
    assert source_obscurity_score(1000) < 0.1
    assert source_obscurity_score(100000) == 0.0
    mid = source_obscurity_score(30)
    assert 0.3 < mid < 0.7


def test_source_obscurity_monotonic_decreasing():
    vals = [source_obscurity_score(n) for n in (0, 5, 50, 500, 5000)]
    assert vals == sorted(vals, reverse=True)


def test_story_obscurity_endpoints():
    assert story_obscurity_score(1) == 1.0
    assert story_obscurity_score(20) <= 0.01  # ~zero
    assert story_obscurity_score(100) == 0.0


def test_story_obscurity_monotonic_decreasing():
    vals = [story_obscurity_score(n) for n in (1, 2, 5, 10, 20)]
    assert vals == sorted(vals, reverse=True)


def test_popularity_score_endpoints():
    assert popularity_score(0, 0) == 0.0
    # At/above the "very viral" cap it clamps to 1.0.
    assert popularity_score(2000, 500) == 1.0
    assert popularity_score(100000, 50000) == 1.0


def test_popularity_score_in_range_and_monotonic():
    vals = [popularity_score(s, 0) for s in (0, 10, 50, 200, 1000, 3000)]
    assert all(0.0 <= v <= 1.0 for v in vals)
    assert vals == sorted(vals)


def test_popularity_score_comments_weighted_double():
    # comments count 2x in the engagement term.
    assert popularity_score(0, 10) == popularity_score(20, 0)


def test_popularity_score_handles_none_and_negative():
    assert popularity_score(None, None) == 0.0
    assert popularity_score(-5, -3) == 0.0


def test_headline_length_empty_and_long():
    assert headline_length_score("") == 0.0
    assert headline_length_score("one two three") < 0.2
    assert headline_length_score(" ".join(["w"] * 30)) == 1.0


def test_headline_length_monotonic():
    vals = [headline_length_score(" ".join(["w"] * n)) for n in (0, 3, 8, 16, 24, 48)]
    assert vals == sorted(vals)
    assert vals[-1] == 1.0


def test_caps_ratio_all_caps():
    assert caps_ratio_score("BREAKING NEWS HUGE") == 1.0


def test_caps_ratio_lowercase():
    assert caps_ratio_score("a quiet headline") == 0.0


def test_caps_ratio_title_case_is_modest():
    r = caps_ratio_score("A Quiet Headline About Things")
    assert 0.0 < r < 0.4


def test_caps_ratio_empty_and_no_letters():
    assert caps_ratio_score("") == 0.0
    assert caps_ratio_score("!!! 123 ???") == 0.0


def test_punctuation_intensity_calm_text():
    assert punctuation_intensity_score("The market closed down today.") == 0.0


def test_punctuation_intensity_heavy_text():
    r = punctuation_intensity_score("Wow!! Really?! Are you sure?!")
    assert r > 0.5


def test_punctuation_intensity_empty():
    assert punctuation_intensity_score("") == 0.0


def test_numeric_density_text_without_numbers():
    assert numeric_density_score("hello world from the office") == 0.0


def test_numeric_density_data_heavy():
    r = numeric_density_score("The S&P fell 2.3% to 4567 amid 12 layoffs.")
    assert r > 0.3


def test_numeric_density_clamped_to_one():
    # Heavy-numbers text: 5 numbers across 5 letter-words -> raw=1.0, *5 -> clamped to 1.0.
    r = numeric_density_score("Stocks 12 fell 34 amid 56 jumps 78 over 90")
    assert r == 1.0


def test_numeric_density_pure_digits_no_words_returns_zero():
    # _WORD_RE is letter-only, so a pure-digits string has zero "words" and
    # the score short-circuits to 0 rather than dividing by zero.
    assert numeric_density_score("1 2 3 4 5") == 0.0


def test_question_headline_yes_and_no():
    assert question_headline_score("Is the economy slowing down?") == 1.0
    assert question_headline_score("The economy is slowing down.") == 0.0
    assert question_headline_score("Are we there yet?   ") == 1.0


def test_question_headline_empty():
    assert question_headline_score("") == 0.0


def test_quote_present_straight_quotes():
    assert quote_present_score('CEO says "we will not back down"') == 1.0


def test_quote_present_smart_quotes():
    assert quote_present_score("Senator: “this is unacceptable”") == 1.0


def test_quote_present_in_summary_only():
    assert quote_present_score("Profit drops", 'analyst said "this was inevitable"') == 1.0


def test_quote_present_no_quote():
    assert quote_present_score("Bank profits drop in second quarter") == 0.0


def test_compute_rules_features_includes_new_keys():
    art = {"title": "WHY did stocks CRASH today??", "summary": '"Markets are spooked," said one analyst, "by 12 events"'}
    src = {"source_lean": 0.0, "source_reputation": 0.5, "category": "business",
           "country": "US", "region": "national"}
    feats = compute_rules_features(art, src)
    for k in ("headline_length", "caps_ratio", "punctuation_intensity",
              "numeric_density", "question_headline", "quote_present"):
        assert k in feats
        assert 0.0 <= feats[k] <= 1.0
    assert feats["question_headline"] == 1.0
    assert feats["quote_present"] == 1.0
    assert feats["caps_ratio"] > 0.3  # WHY, CRASH heavy
    assert feats["punctuation_intensity"] > 0.0


def test_popularity_poll_wrapper_matches_shared_formula():
    import os
    import sys
    HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if os.path.join(HERE, "jobs") not in sys.path:
        sys.path.insert(0, os.path.join(HERE, "jobs"))
    from popularity_poll import _popularity_score
    for s, c in ((0, 0), (10, 5), (500, 100), (2000, 500), (99999, 1)):
        assert _popularity_score(s, c) == popularity_score(s, c)
