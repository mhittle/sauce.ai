from app.classifier.rules import simhash64, hamming64, article_simhash


def test_simhash_empty_is_zero():
    assert simhash64("") == 0
    assert simhash64(None) == 0


def test_simhash_is_deterministic():
    assert simhash64("Trump signs sweeping tariff bill into law") \
        == simhash64("Trump signs sweeping tariff bill into law")


def test_simhash_fits_in_64_bits():
    h = simhash64("Fed holds rates steady at 5.25 percent, signals patience")
    assert 0 <= h < (1 << 64)


def test_simhash_case_and_punctuation_insensitive():
    a = simhash64("Trump signs sweeping tariff bill into law")
    b = simhash64("TRUMP SIGNS SWEEPING TARIFF BILL INTO LAW!!")
    assert a == b


def test_simhash_near_duplicates_have_small_hamming():
    # Near-identical (one-word swap / punctuation) should land within HD<=5
    # which is the production clustering threshold.
    a = simhash64("Trump signs sweeping tariff bill into law on Monday")
    b = simhash64("Trump signs sweeping tariff bill into law Monday")
    assert hamming64(a, b) <= 5


def test_simhash_unrelated_have_large_hamming():
    a = simhash64("Trump signs sweeping tariff bill into law on Monday")
    b = simhash64("Scientists discover new exoplanet around Proxima Centauri")
    assert hamming64(a, b) > 20


def test_hamming64_basic():
    assert hamming64(0, 0) == 0
    assert hamming64(0, 1) == 1
    assert hamming64(0xFFFFFFFFFFFFFFFF, 0) == 64
    assert hamming64(0b1010, 0b0101) == 4


def test_article_simhash_uses_summary_to_disambiguate():
    # Same generic headline, different stories via summary lead. Should not
    # cluster as near-duplicates.
    a = article_simhash(
        "Court rules in landmark case",
        "The Supreme Court today ruled that affirmative action programs at universities are unconstitutional, in a 6-3 decision authored by Chief Justice Roberts.",
    )
    b = article_simhash(
        "Court rules in landmark case",
        "A federal appeals court in Texas ruled that the state's new abortion ban is constitutional, upholding a lower-court decision from January.",
    )
    assert hamming64(a, b) > 3


def test_article_simhash_clusters_byline_variant_reprints():
    # Same wire body with a different headline (typical AP/Reuters
    # re-headline by a partner outlet). Lands within the production HD<=8
    # clustering threshold.
    a = article_simhash(
        "Fed holds rates steady",
        "The Federal Reserve voted to leave its benchmark interest rate unchanged at the 5.25-5.5 percent range, citing persistent inflation.",
    )
    b = article_simhash(
        "Fed leaves rates unchanged",
        "The Federal Reserve voted to leave its benchmark interest rate unchanged at the 5.25-5.5 percent range, citing persistent inflation.",
    )
    assert hamming64(a, b) <= 8


def test_article_simhash_rejects_unrelated_when_headlines_share_words():
    # Common-words-in-headline trap: both contain "court rules" but the
    # summaries describe entirely different stories. Should NOT cluster under
    # the production HD<=8 threshold.
    a = article_simhash(
        "Court rules in landmark affirmative-action case",
        "The Supreme Court today ruled that race-based admissions at universities are unconstitutional in a 6-3 decision authored by Chief Justice Roberts.",
    )
    b = article_simhash(
        "Court rules in landmark abortion case",
        "A federal appeals court in Texas ruled that the state's new abortion ban is constitutional, upholding a lower-court decision from January.",
    )
    assert hamming64(a, b) > 8
