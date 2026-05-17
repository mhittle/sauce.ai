"""English-only article filter.

Used by `fetch_feeds.py` to drop non-English entries at insert time.

Strategy (first positive non-English signal wins; permissive otherwise):
1. If the RSS feed declared a non-English `<language>` tag, trust it and
   reject. English-tagged or untagged feeds still get checked further
   because plenty of multilingual outlets either omit the tag or
   mislabel it as `en`.
2. Script check: count letter characters in title (plus summary as
   filler) and reject if the share outside the Latin script ranges
   exceeds NON_LATIN_THRESHOLD. Fast path that cleanly catches
   Japanese, Korean, Chinese, Arabic, Hebrew, Cyrillic, Greek,
   Devanagari, Thai, etc. without invoking the language detector.
3. Latin-script language detection (BUG-013): the script check cannot
   tell English from German/Spanish/Finnish/etc. — they all use Latin
   letters. When there's enough text, run `langdetect` and reject only
   when it is *confident* the text is a non-English language and
   English is an unlikely alternative. Deliberately biased toward
   keeping English: a dropped real English article is a more visible
   regression than an occasional foreign one slipping through.

Detector calls never raise into the fetch loop — any langdetect
failure, missing model features, or import problem falls through to
accept (permissive by default).
"""

NON_LATIN_THRESHOLD = 0.25
_ENGLISH_LANG_TAGS = {"en", "english"}

# langdetect stage tuning. Only run the detector when there's enough
# signal, and only reject on a confident non-English call with English
# a poor alternative — short headlines are noisy and over-filtering
# English is worse than under-filtering foreign content.
MIN_DETECT_LETTERS = 24
LANGDETECT_MIN_CONFIDENCE = 0.85
LANGDETECT_ENGLISH_FLOOR = 0.10

_detector_seeded = False


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


def _latin_letter_count(text):
    return sum(1 for ch in text if _is_latin_letter(ch))


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


def _detect_lang_probs(text):
    """Return {lang_code: probability} from langdetect, or None.

    Broad except is intentional: this runs inside the per-entry fetch
    loop. langdetect raises on featureless input and the import may be
    absent in some environments; in every failure case the caller must
    fall through to accept rather than break the pipeline.
    """
    global _detector_seeded
    try:
        from langdetect import detect_langs, DetectorFactory

        if not _detector_seeded:
            DetectorFactory.seed = 0
            _detector_seeded = True
        return {item.lang: item.prob for item in detect_langs(text)}
    except Exception:
        return None


def is_english(title, summary="", feed_language=None):
    """Return True if the article looks English enough to keep.

    Permissive by default: empty / unknown / weird / too-short inputs
    accept. The filter only rejects on a clear positive non-English
    signal (a non-English feed declaration, a meaningful share of
    non-Latin letters, or a confident non-English langdetect call).
    """
    norm = _normalize_lang(feed_language)
    if norm and norm not in _ENGLISH_LANG_TAGS:
        return False

    text = (title or "") + " " + (summary or "")
    if _non_latin_letter_ratio(text) >= NON_LATIN_THRESHOLD:
        return False

    if _latin_letter_count(text) < MIN_DETECT_LETTERS:
        return True

    probs = _detect_lang_probs(text)
    if not probs:
        return True

    english_prob = probs.get("en", 0.0)
    top_lang = max(probs, key=probs.get)
    top_prob = probs[top_lang]
    if (
        top_lang != "en"
        and top_prob >= LANGDETECT_MIN_CONFIDENCE
        and english_prob < LANGDETECT_ENGLISH_FLOOR
    ):
        return False
    return True
