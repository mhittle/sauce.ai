"""English-only article filter.

Pure-Python heuristic used by `fetch_feeds.py` to drop non-English entries
at insert time. No external dependencies.

Strategy:
1. If the RSS feed declared a non-English `<language>` tag, trust it and
   reject. English-tagged or untagged feeds still get script-checked
   because plenty of multilingual outlets either omit the tag or
   mislabel it as `en`.
2. Otherwise count letter characters in the article's title (plus summary
   as filler) and reject if the share that fall outside the Latin script
   ranges exceeds NON_LATIN_THRESHOLD. This cleanly catches Japanese,
   Korean, Chinese, Arabic, Hebrew, Cyrillic, Greek, Devanagari, Thai,
   etc.

Known limitation: Latin-script European content (French, German,
Spanish, Italian, Dutch, etc.) reads as English by this heuristic and
slips through. Acceptable for v1; flagged in INSTALL.txt §10.
"""

NON_LATIN_THRESHOLD = 0.25
_ENGLISH_LANG_TAGS = {"en", "english"}


def _normalize_lang(tag):
    if not tag:
        return ""
    return str(tag).strip().lower().replace("_", "-").split("-")[0]


def _is_latin_letter(ch):
    if not ch.isalpha():
        return False
    cp = ord(ch)
    # Basic Latin (A-z), Latin-1 Supplement, Latin Extended-A/B, IPA
    # Extensions, Latin Extended Additional. Covers every Western/Central
    # European alphabet including Polish, Czech, Turkish, Vietnamese.
    if cp <= 0x024F:
        return True
    if 0x1E00 <= cp <= 0x1EFF:
        return True
    return False


def _non_latin_letter_ratio(text):
    total = 0
    non_latin = 0
    for ch in text:
        if not ch.isalpha():
            continue
        total += 1
        if not _is_latin_letter(ch):
            non_latin += 1
    if total == 0:
        return 0.0
    return non_latin / total


def is_english(title, summary="", feed_language=None):
    """Return True if the article looks English enough to keep.

    Permissive by default: empty / unknown / weird inputs accept. The
    filter only rejects on clear positive signal (non-English feed
    declaration, or a meaningful share of non-Latin letters).
    """
    norm = _normalize_lang(feed_language)
    if norm and norm not in _ENGLISH_LANG_TAGS:
        return False
    text = (title or "") + " " + (summary or "")
    return _non_latin_letter_ratio(text) < NON_LATIN_THRESHOLD
