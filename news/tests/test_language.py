"""Unit tests for the English-only article filter.

`langdetect` is stubbed via sys.modules (same pattern as the
trafilatura/anthropic stubs elsewhere in the suite) so detection is
fully scripted and the tests pass whether or not the package is
installed in the environment.
"""
import sys
import types

import pytest

import app.language as language
from app.language import is_english, _non_latin_letter_ratio, _normalize_lang


class _Lang:
    def __init__(self, lang, prob):
        self.lang = lang
        self.prob = prob


@pytest.fixture(autouse=True)
def fake_langdetect(monkeypatch):
    """Install a scripted fake `langdetect`.

    Default: everything that reaches the detector reads as confident
    English, so the permissive/English-accept cases stay deterministic.
    Tests opt into other outcomes via `.set(...)` or `.raise_on_detect()`.
    """
    state = {"default": [("en", 0.99)], "map": {}, "raise": False}

    def detect_langs(text):
        if state["raise"]:
            raise RuntimeError("no features in text")
        for needle, langs in state["map"].items():
            if needle in text:
                return [_Lang(code, p) for code, p in langs]
        return [_Lang(code, p) for code, p in state["default"]]

    fake = types.ModuleType("langdetect")
    fake.detect_langs = detect_langs
    fake.DetectorFactory = type("DetectorFactory", (), {"seed": None})
    monkeypatch.setitem(sys.modules, "langdetect", fake)
    monkeypatch.setattr(language, "_detector_seeded", False)

    class Control:
        def set(self, needle, langs):
            state["map"][needle] = langs

        def raise_on_detect(self):
            state["raise"] = True

    return Control()


def test_plain_english_title_accepts():
    assert is_english("Federal Reserve holds rates steady") is True


def test_english_title_with_en_us_tag_accepts():
    assert is_english("Markets rally on jobs data", feed_language="en-US") is True


def test_english_title_with_uppercase_tag_accepts():
    assert is_english("Storm batters East Coast", feed_language="ENGLISH") is True


def test_japanese_feed_tag_rejects_even_if_title_latin():
    # A wrongly-romanized headline on an explicitly Japanese feed should be
    # rejected because we trust the declaration over the title content.
    assert is_english("Tokyo news roundup", feed_language="ja") is False


def test_german_feed_tag_rejects():
    assert is_english("Bundesliga news", feed_language="de-DE") is False


def test_japanese_title_rejects_via_script_check():
    assert is_english("東京で大規模な地震が発生") is False


def test_chinese_title_rejects():
    assert is_english("中国宣布新的经济政策") is False


def test_korean_title_rejects():
    assert is_english("서울에서 대규모 집회가 열렸다") is False


def test_arabic_title_rejects():
    assert is_english("الرئيس يلقي خطاباً في الأمم المتحدة") is False


def test_russian_title_rejects():
    assert is_english("Президент выступил с заявлением") is False


def test_hindi_title_rejects():
    assert is_english("प्रधानमंत्री ने नई योजना की घोषणा की") is False


def test_mostly_english_title_with_one_japanese_word_accepts():
    # A small share of non-Latin letters shouldn't tip the title over the
    # NON_LATIN_THRESHOLD of 0.25.
    assert is_english("Tokyo restaurant 寿司 reopens after fire") is True


def test_latin_extended_accents_accept():
    # Café, naïve, jalapeño — Latin-1 / Extended-A. Must not be flagged.
    assert is_english("Café opens in São Paulo amid jalapeño shortage") is True


def test_vietnamese_diacritics_accept():
    # Vietnamese uses Latin Extended Additional (0x1E00-0x1EFF). Script
    # check accepts; detector (stubbed English by default) also accepts.
    assert is_english("Phở restaurant chain expands to Hà Nội suburbs") is True


def test_empty_title_accepts():
    # Default permissive when there's nothing to judge.
    assert is_english("") is True


def test_none_title_does_not_crash():
    assert is_english(None) is True


def test_summary_fills_in_when_title_short():
    # Short ASCII title plus a CJK-heavy summary should still reject.
    assert is_english("Update", summary="アジア株式市場は本日大幅に下落しました") is False


# --- BUG-013: Latin-script European leakage via langdetect stage ---


def test_german_latin_text_rejected_by_detector(fake_langdetect):
    fake_langdetect.set("Bundesregierung", [("de", 0.99)])
    assert is_english(
        "Bundesregierung beschliesst neues Gesetz zur Energiewende"
    ) is False


def test_spanish_latin_text_rejected_by_detector(fake_langdetect):
    fake_langdetect.set("Gobierno", [("es", 0.99)])
    assert is_english(
        "El Gobierno anuncia nuevas medidas economicas para el proximo ano"
    ) is False


def test_finnish_latin_text_rejected_by_detector(fake_langdetect):
    # The hs.fi case from the bug report (Finnish sports headline).
    fake_langdetect.set("jalkapallo", [("fi", 0.99)])
    assert is_english(
        "Suomen jalkapallomaajoukkue voitti tarkean ottelun eilen illalla"
    ) is False


def test_english_still_accepted_when_detector_says_english(fake_langdetect):
    fake_langdetect.set("Federal Reserve", [("en", 0.99)])
    assert is_english(
        "Federal Reserve signals it may hold interest rates steady next quarter"
    ) is True


def test_short_latin_text_skips_detector_and_accepts(fake_langdetect):
    # Below MIN_DETECT_LETTERS the detector is never consulted even if it
    # would flag the text — too little signal to risk over-filtering.
    fake_langdetect.set("Bonn", [("de", 0.99)])
    assert is_english("Bonn vote") is True


def test_low_confidence_foreign_call_accepts(fake_langdetect):
    # Detector leans German but below LANGDETECT_MIN_CONFIDENCE — keep it.
    fake_langdetect.set("Berlin", [("de", 0.70), ("en", 0.20)])
    assert is_english(
        "Berlin summit produces a joint statement on regional security"
    ) is True


def test_foreign_top_but_english_plausible_accepts(fake_langdetect):
    # Confident-ish Spanish, but English is a real alternative (>= floor):
    # bias toward keeping English rather than dropping a real article.
    fake_langdetect.set("Barcelona", [("es", 0.86), ("en", 0.13)])
    assert is_english(
        "Barcelona club statement addresses the financial fair play review"
    ) is True


def test_detector_exception_falls_through_to_accept(fake_langdetect):
    # langdetect raising (featureless text, missing model) must never
    # break the fetch loop — permissive accept.
    fake_langdetect.raise_on_detect()
    assert is_english(
        "Some otherwise unremarkable English headline about local sports"
    ) is True


def test_detector_unavailable_falls_through_to_accept(monkeypatch):
    # If langdetect isn't importable at all, accept (don't break fetch).
    monkeypatch.setitem(sys.modules, "langdetect", None)
    assert is_english(
        "Another perfectly ordinary English news headline goes here today"
    ) is True


def test_normalize_lang_strips_region_and_case():
    assert _normalize_lang("en-US") == "en"
    assert _normalize_lang("EN_GB") == "en"
    assert _normalize_lang("  ja-JP ") == "ja"
    assert _normalize_lang(None) == ""
    assert _normalize_lang("") == ""


def test_non_latin_ratio_pure_ascii_zero():
    assert _non_latin_letter_ratio("Hello world 123!") == 0.0


def test_non_latin_ratio_pure_cjk_one():
    assert _non_latin_letter_ratio("東京新聞") == 1.0


def test_non_latin_ratio_ignores_digits_and_punctuation():
    # Only letters count toward the ratio.
    assert _non_latin_letter_ratio("123 !!! ???") == 0.0
