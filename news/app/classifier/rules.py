"""Cheap deterministic features. No network, no LLM."""
import re
import math

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]+")
_SENT_RE = re.compile(r"[.!?]+")
_VOWELS = "aeiouy"


def _strip_html(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"<[^>]+>", " ", text)


def _count_syllables(word: str) -> int:
    word = word.lower()
    if not word:
        return 0
    count = 0
    prev_vowel = False
    for ch in word:
        is_vowel = ch in _VOWELS
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel
    if word.endswith("e") and count > 1:
        count -= 1
    return max(count, 1)


def flesch_kincaid_grade(text: str) -> float:
    text = _strip_html(text)
    words = _WORD_RE.findall(text)
    if not words:
        return 0.0
    sentences = [s for s in _SENT_RE.split(text) if s.strip()]
    n_sent = max(len(sentences), 1)
    n_syl = sum(_count_syllables(w) for w in words)
    grade = 0.39 * (len(words) / n_sent) + 11.8 * (n_syl / len(words)) - 15.59
    return max(0.0, grade)


def normalized_reading_level(text: str) -> float:
    """Map FK grade 0..20 -> 0..1."""
    g = flesch_kincaid_grade(text)
    return max(0.0, min(1.0, g / 20.0))


_CAP_TOKEN = re.compile(r"\b[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,3}")
_NUM_RE = re.compile(r"\b\d[\d,.\-/%]*\b")


def info_density(text: str) -> float:
    """Entity+number density per token. Crude but cheap. Returns 0..1."""
    text = _strip_html(text)
    words = _WORD_RE.findall(text)
    if not words:
        return 0.0
    entities = len(_CAP_TOKEN.findall(text))
    nums = len(_NUM_RE.findall(text))
    raw = (entities + nums) / max(len(words), 1)
    # squashing: typical news ~0.05-0.25
    return max(0.0, min(1.0, raw * 3.0))


def normalize_byline(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"^\s*by\s+", "", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s[:200]


def split_bylines(s: str):
    if not s:
        return []
    parts = re.split(r"\s*(?:,|;|/| and | & )\s*", s, flags=re.I)
    out = []
    for p in parts:
        n = normalize_byline(p)
        if n and not n.startswith("the ") and len(n) >= 3:
            out.append(n)
    return out[:5]


def compute_rules_features(article: dict, source: dict) -> dict:
    """article: {title, summary}.  source: {source_lean, source_reputation, category, country, region}."""
    text = f"{article.get('title','')}. {_strip_html(article.get('summary',''))}"
    return {
        "reading_level": normalized_reading_level(text),
        "info_density": info_density(text),
        "source_lean": float(source.get("source_lean", 0)),
        "source_reputation": float(source.get("source_reputation", 0.5)),
        "category": source.get("category", "general"),
        "country": source.get("country", "US"),
        "region": source.get("region", "national"),
        "journalist_reputation": float(source.get("source_reputation", 0.5)),  # placeholder; maintenance.py refines
    }
