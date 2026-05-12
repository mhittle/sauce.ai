from app.classifier.rules import (
    flesch_kincaid_grade, normalized_reading_level, info_density,
    normalize_byline, split_bylines, compute_rules_features,
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
