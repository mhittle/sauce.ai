"""Cheap deterministic features. No network, no LLM."""
import hashlib
import math
import re

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]+")
_SENT_RE = re.compile(r"[.!?]+")
_VOWELS = "aeiouy"
_TITLE_PUNCT_RE = re.compile(r"[^a-z0-9 ]+")
_WS_RE = re.compile(r"\s+")


def normalize_title(title: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace. Used for title_hash
    so different sources publishing the same story group together."""
    if not title:
        return ""
    t = _TITLE_PUNCT_RE.sub(" ", title.lower())
    t = _WS_RE.sub(" ", t).strip()
    return t


def title_hash(title: str) -> str:
    """SHA1 of the normalized title. Matches the SQL `SHA1(REGEXP_REPLACE(LOWER(title), ...))`
    used in the obscurity migration so backfilled and runtime values line up."""
    return hashlib.sha1(normalize_title(title).encode("utf-8", "ignore")).hexdigest()


_SIMHASH_STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "is", "on", "for", "and", "or",
    "at", "by", "with", "from", "that", "this", "as", "it", "be", "are",
    "was", "were", "has", "have", "had", "but", "not", "no", "into",
    "after", "before", "over", "under", "out", "up", "down", "off",
}
_SIMHASH_TOKEN_RE = re.compile(r"[a-z0-9]+")


def simhash64(text: str) -> int:
    """64-bit SimHash over tokenized text. Returns 0 for empty input.

    Used for fuzzy article clustering: Hamming distance <= ~3 between two
    simhashes implies near-duplicate content. Pure Python; no deps. Token
    hash is md5 (not security-sensitive, just stable + well-distributed).
    """
    if not text:
        return 0
    tokens = [t for t in _SIMHASH_TOKEN_RE.findall(text.lower())
              if t not in _SIMHASH_STOPWORDS and len(t) > 1]
    if not tokens:
        return 0
    vec = [0] * 64
    for tok in tokens:
        h = int(hashlib.md5(tok.encode("utf-8", "ignore")).hexdigest()[:16], 16)
        for i in range(64):
            if (h >> i) & 1:
                vec[i] += 1
            else:
                vec[i] -= 1
    out = 0
    for i in range(64):
        if vec[i] >= 0:
            out |= (1 << i)
    return out


def hamming64(a: int, b: int) -> int:
    return bin((a ^ b) & ((1 << 64) - 1)).count("1")


def article_simhash(title: str, summary: str = "") -> int:
    """SimHash input is title + first ~200 chars of plaintext summary. The
    summary lead disambiguates near-duplicate titles ('Trump signs bill')
    that would otherwise over-cluster."""
    body = _strip_html(summary or "")[:200]
    return simhash64(f"{title or ''} {body}")


def source_obscurity_score(article_count_30d: int) -> float:
    """Log-scale: tiny source = 1.0, ~1000 articles/30d source = 0.0.
    count=1 -> ~0.9, count=10 -> ~0.67, count=100 -> ~0.33, count>=1000 -> 0."""
    n = max(0, int(article_count_30d or 0))
    if n == 0:
        return 1.0
    s = math.log10(n + 1) / 3.0  # log10(1001) ≈ 3
    return max(0.0, min(1.0, 1.0 - s))


def story_obscurity_score(cluster_count: int) -> float:
    """Log-scale: only this story = 1.0, ~20 sources covering same story = 0.0."""
    n = max(1, int(cluster_count or 1))
    s = math.log10(n) / math.log10(20)  # ~1.3
    return max(0.0, min(1.0, 1.0 - s))


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
