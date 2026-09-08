"""Claim — health-headline reality check. Pure helpers.

No Flask, no DB, no SDK imports: span validation (the anti-hallucination
rule — a field whose verbatim abstract span is not found is dropped),
citation normalization, relative-to-absolute effect math, the closed
spin-flag list, the deterministic grade rubric, and the health-text gate.
The Flask glue lives in `app.routes.claim`; the HTTP resolvers in
`app.claim_sources`; the model calls in `app.classifier.claim_llm`.

The rubric grades *reporting*, never treatment. The model never emits a
grade: `grade()` is a fixed table over the validated fields.
"""
import re

SPIN_FLAGS = (
    "causal-language-on-observational",
    "animal-or-in-vitro-reported-as-human",
    "surrogate-as-hard-outcome",
    "relative-only",
    "no-study-located",
    "single-study-as-consensus",
    "preprint-unlabeled",
    "press-release-source",
    "sample-under-50",
)

FLAG_LABELS = {
    "causal-language-on-observational": "Causal language on an observational study",
    "animal-or-in-vitro-reported-as-human": "Animal or lab-dish study reported as if in humans",
    "surrogate-as-hard-outcome": "Surrogate marker presented as a hard outcome",
    "relative-only": "Relative risk without the absolute numbers",
    "no-study-located": "No study could be located",
    "single-study-as-consensus": "One study presented as settled science",
    "preprint-unlabeled": "Preprint not labeled as such",
    "press-release-source": "Sourced from a press release",
    "sample-under-50": "Fewer than 50 participants",
}

DESIGNS = (
    "meta-analysis", "rct", "cohort", "case-control", "cross-sectional",
    "case-series", "animal", "in-vitro", "other",
)
SPECIES = ("human", "animal", "in-vitro", "other")
EFFECT_TYPES = ("RR", "OR", "HR", "MD", "other")
OUTCOME_TYPES = ("hard", "surrogate", "unclear")
PEER_REVIEW = ("peer-reviewed", "preprint", "unclear")

# Design tier -> base grains. 1 = best evidence; 5 = nothing to stand on.
_DESIGN_TIER = {
    "meta-analysis": 1, "rct": 1,
    "cohort": 2, "case-control": 2,
    "cross-sectional": 3, "case-series": 3, "other": 3,
    "animal": 4, "in-vitro": 4,
}

GRAIN_LABELS = {
    1: "Solid — the headline tracks strong evidence",
    2: "Reasonable — good evidence, read the caveats",
    3: "Take with salt — weak design or the headline drifts",
    4: "Heavy salt — not in humans, tiny, or the headline overreaches",
    5: "No basis — no locatable study behind this",
}

SMALL_SAMPLE = 50
OR_CONVERSION_MAX_BASELINE = 0.10

_WS = re.compile(r"\s+")
_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>\]]+", re.IGNORECASE)
_PMID_RE = re.compile(r"\bPMID:?\s*(\d{1,9})\b", re.IGNORECASE)
_TRAILING_PUNCT = ".,;:]}>\"'"

_HEALTH_TERMS = (
    "study", "studies", "trial", "randomized", "randomised", "placebo",
    "risk", "patients", "participants", "cohort", "mice", "rats", "dose",
    "mortality", "cancer", "diabetes", "cardiovascular", "heart disease",
    "dementia", "alzheimer", "stroke", "obesity", "blood pressure",
    "cholesterol", "vaccine", "infection", "virus", "clinical", "researchers",
    "journal", "lancet", "jama", "nejm", "new england journal", "bmj",
    "nature medicine", "meta-analysis", "systematic review", "peer-reviewed",
    "epidemiolog", "odds ratio", "hazard ratio", "relative risk", "supplement",
    "diet", "exercise", "sleep", "microbiome", "gut", "inflammation", "hormone",
    "protein", "longevity", "aging", "lifespan", "symptoms", "diagnos",
    "treatment", "therapy", "drug", "fda", "cdc", "who ", "nih",
)
_HEALTH_MIN_HITS = 2
_HEALTH_HEAD_CHARS = 1500

_ANIMAL_WORDS = (
    "mice", "mouse", "rat", "rats", "rodent", "animal", "zebrafish", "monkey",
    "macaque", "dog", "dogs", "pig", "pigs", "cell", "cells", "in vitro",
    "petri", "lab dish", "test tube", "worm", "worms", "fly", "flies", "fruit fl",
)


def normalize_ws(text):
    return _WS.sub(" ", (text or "")).strip()


def normalize_doi(raw):
    """Canonical lowercase DOI or None. Accepts `doi:`, `https://doi.org/`,
    `dx.doi.org` prefixes and trailing punctuation from prose."""
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip()
    s = re.sub(r"^(https?://)?(dx\.)?doi\.org/", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^doi:\s*", "", s, flags=re.IGNORECASE)
    m = _DOI_RE.search(s)
    if not m:
        return None
    doi = m.group(0).rstrip(_TRAILING_PUNCT)
    # Lancet-style DOIs carry balanced parentheses; a trailing unbalanced
    # one is prose punctuation.
    while doi.endswith(")") and doi.count(")") > doi.count("("):
        doi = doi[:-1].rstrip(_TRAILING_PUNCT)
    return doi.lower()


def normalize_pmid(raw):
    """Digits-only PMID or None. Accepts `12345678` and `PMID: 12345678`."""
    if raw is None:
        return None
    s = str(raw).strip()
    m = re.match(r"^(?:pmid:?\s*)?(\d{1,9})$", s, re.IGNORECASE)
    return m.group(1) if m else None


def find_dois(text):
    out = []
    for m in _DOI_RE.finditer(text or ""):
        doi = normalize_doi(m.group(0))
        if doi and doi not in out:
            out.append(doi)
    return out


def find_pmids(text):
    out = []
    for m in _PMID_RE.finditer(text or ""):
        if m.group(1) not in out:
            out.append(m.group(1))
    return out


def url_hash(url):
    import hashlib
    u = (url or "").strip()
    u = re.sub(r"#.*$", "", u)
    u = re.sub(r"[?&](utm_[a-z]+|fbclid|gclid)=[^&]*", "", u)
    u = u.rstrip("?&/").lower()
    return hashlib.sha256(u.encode("utf-8")).hexdigest()


def span_in_text(span, text):
    """Whitespace- and case-insensitive verbatim containment."""
    if not span or not text:
        return False
    return normalize_ws(span).lower() in normalize_ws(text).lower()


def _number_forms(value):
    """Strings a number may legitimately take inside an abstract span:
    `0.62`, `.62`, `62%`, `62`, `1,204`."""
    forms = set()
    try:
        f = float(value)
    except (TypeError, ValueError):
        return forms
    if f == int(f):
        i = int(f)
        forms.add(str(i))
        forms.add(f"{i:,}")
    s = f"{f:.4f}".rstrip("0").rstrip(".")
    forms.add(s)
    if s.startswith("0."):
        forms.add(s[1:])
    if s.startswith("-0."):
        forms.add("-" + s[2:])
    pct = f * 100
    p = f"{pct:.2f}".rstrip("0").rstrip(".")
    forms.add(p)
    forms.add(p + "%")
    return forms


def number_in_span(value, span):
    if value is None:
        return False
    s = normalize_ws(span)
    if not s:
        return False
    return any(form and form in s for form in _number_forms(value))


_SPAN_FIELDS = (
    "design", "species", "n", "population", "exposure", "comparator",
    "outcome", "outcome_type", "follow_up", "baseline_risk", "funding",
    "peer_review",
)


def _coerce_enum(value, allowed):
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    return v if v in allowed else None


def validate_spans(fields, abstract):
    """Drop every extracted field whose `span` is not verbatim in the
    abstract, and every numeric field whose value does not appear in its
    own span. Returns a new dict of the surviving fields, each as
    `{"value": ..., "span": ...}` (effect keeps its full shape)."""
    if not isinstance(fields, dict) or not abstract:
        return {}
    out = {}
    for key in _SPAN_FIELDS:
        item = fields.get(key)
        if not isinstance(item, dict):
            continue
        value = item.get("value")
        span = item.get("span")
        if value is None or value == "" or not span_in_text(span, abstract):
            continue
        if key == "design":
            value = _coerce_enum(value, DESIGNS)
        elif key == "species":
            value = _coerce_enum(value, SPECIES)
        elif key == "outcome_type":
            value = _coerce_enum(value, OUTCOME_TYPES)
        elif key == "peer_review":
            value = _coerce_enum(value, PEER_REVIEW)
        elif key == "n":
            try:
                value = int(value)
            except (TypeError, ValueError):
                continue
            if value <= 0 or not number_in_span(value, span):
                continue
        elif key == "baseline_risk":
            value = _as_proportion(value)
            if value is None or not number_in_span(value, span):
                continue
        elif isinstance(value, str):
            value = normalize_ws(value)[:400]
        else:
            continue
        if value is None:
            continue
        out[key] = {"value": value, "span": normalize_ws(span)[:600]}

    effect = fields.get("effect")
    if isinstance(effect, dict) and span_in_text(effect.get("span"), abstract):
        etype = effect.get("type")
        etype = etype.strip().upper() if isinstance(etype, str) else ""
        if etype == "OTHER":
            etype = "other"
        point = _as_float(effect.get("point"))
        span = effect.get("span")
        if etype in EFFECT_TYPES and point is not None and number_in_span(point, span):
            ci_low = _as_float(effect.get("ci_low"))
            ci_high = _as_float(effect.get("ci_high"))
            if ci_low is not None and not number_in_span(ci_low, span):
                ci_low = None
            if ci_high is not None and not number_in_span(ci_high, span):
                ci_high = None
            if (ci_low is None) != (ci_high is None):
                ci_low = ci_high = None
            out["effect"] = {
                "type": etype, "point": point,
                "ci_low": ci_low, "ci_high": ci_high,
                "span": normalize_ws(span)[:600],
            }
    return out


def _as_float(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _as_proportion(v):
    """Baseline risk may arrive as 0.12, 12, or "12%". Normalize to [0,1]."""
    if isinstance(v, str):
        v = v.strip().rstrip("%")
    f = _as_float(v)
    if f is None or f < 0:
        return None
    if f > 1.0:
        f = f / 100.0
    if f > 1.0:
        return None
    return f


def _fmt(x, nd=1):
    if x is None:
        return None
    return round(x, nd)


def absolute_effect(effect, baseline):
    """Translate a relative measure into absolute terms given a baseline
    (control-group) risk as a proportion. Returns a dict the card renders
    from; every key is present so the template never branches on
    existence. Never invents a baseline: when it is missing the result is
    the relative figure alone with `baseline_missing=True`."""
    out = {
        "type": None, "point": None, "ci_low": None, "ci_high": None,
        "baseline_missing": baseline is None,
        "baseline_pct": None, "treated_pct": None,
        "arr_pct": None, "arr_ci_low_pct": None, "arr_ci_high_pct": None,
        "direction": None, "nnt": None, "nnt_kind": None,
        "icon_control": None, "icon_treated": None,
        "converted_from_or": False, "notes": [],
    }
    if not effect:
        return out
    etype = effect.get("type")
    point = _as_float(effect.get("point"))
    out.update({"type": etype, "point": point,
                "ci_low": _as_float(effect.get("ci_low")),
                "ci_high": _as_float(effect.get("ci_high"))})
    if point is None:
        return out
    if etype in ("MD", "other"):
        out["notes"].append("Reported as a difference in means, not a risk; no per-100 translation.")
        return out
    if baseline is None:
        out["notes"].append("The abstract gives no baseline risk, so the absolute effect cannot be computed.")
        return out
    if etype == "OR":
        if baseline >= OR_CONVERSION_MAX_BASELINE:
            out["notes"].append(
                "Odds ratio with a baseline risk over 10%: odds overstate risk here, "
                "so the ratio is shown without an absolute translation.")
            return out
        ratios = [_or_to_rr(r, baseline) for r in (point, out["ci_low"], out["ci_high"])]
        out["converted_from_or"] = True
        out["notes"].append("Odds ratio converted to a risk ratio at the reported baseline (baseline under 10%).")
    else:
        ratios = [point, out["ci_low"], out["ci_high"]]
        if etype == "HR":
            out["notes"].append("Hazard ratio treated as a risk ratio over the study's follow-up (approximation).")
    rr, rr_low, rr_high = ratios
    treated = min(1.0, max(0.0, baseline * rr))
    arr = baseline - treated
    out["baseline_pct"] = _fmt(baseline * 100)
    out["treated_pct"] = _fmt(treated * 100)
    out["arr_pct"] = _fmt(arr * 100)
    if rr_low is not None and rr_high is not None:
        lo = baseline - min(1.0, baseline * rr_high)
        hi = baseline - min(1.0, baseline * rr_low)
        out["arr_ci_low_pct"] = _fmt(lo * 100)
        out["arr_ci_high_pct"] = _fmt(hi * 100)
    if arr > 0:
        out["direction"] = "fewer"
        out["nnt_kind"] = "NNT"
    elif arr < 0:
        out["direction"] = "more"
        out["nnt_kind"] = "NNH"
    else:
        out["direction"] = "same"
    if arr != 0:
        out["nnt"] = int(round(1.0 / abs(arr))) if abs(arr) >= 0.0005 else None
    out["icon_control"] = int(round(baseline * 100))
    out["icon_treated"] = int(round(treated * 100))
    return out


def _or_to_rr(odds_ratio, baseline):
    if odds_ratio is None:
        return None
    return odds_ratio / (1.0 - baseline + baseline * odds_ratio)


def deterministic_flags(fields, *, study_found, headline, claim_text="",
                        article_text="", source_kind=None, study_is_preprint=False):
    """Flags computable from the validated fields alone (no model
    judgment). `article_text` is the news body, used for the labelled-
    preprint check; `study_is_preprint` is the resolver's venue-based
    read (medRxiv, posted-content), which counts as provenance too."""
    flags = []
    if not study_found:
        return ["no-study-located"]
    fields = fields or {}
    n = (fields.get("n") or {}).get("value")
    if isinstance(n, int) and n < SMALL_SAMPLE:
        flags.append("sample-under-50")
    species = (fields.get("species") or {}).get("value")
    design = (fields.get("design") or {}).get("value")
    non_human = species in ("animal", "in-vitro") or design in ("animal", "in-vitro")
    if non_human:
        head = f"{headline or ''} {claim_text or ''}".lower()
        if not any(w in head for w in _ANIMAL_WORDS):
            flags.append("animal-or-in-vitro-reported-as-human")
    peer = (fields.get("peer_review") or {}).get("value")
    if (peer == "preprint" or study_is_preprint) and "preprint" not in (article_text or "").lower():
        flags.append("preprint-unlabeled")
    if source_kind == "press-release":
        flags.append("press-release-source")
    effect = fields.get("effect") or {}
    if effect.get("type") in ("RR", "OR", "HR") and "baseline_risk" not in fields:
        flags.append("relative-only")
    return flags


def merge_flags(deterministic, model_flags):
    """Union of code-derived and model-selected flags, restricted to the
    closed list, deterministic first, each with a one-line `why`.
    `model_flags` is a list of `{"flag": str, "why": str}` (tolerant)."""
    out = []
    seen = set()
    for f in deterministic or []:
        if f in SPIN_FLAGS and f not in seen:
            seen.add(f)
            out.append({"flag": f, "why": _DEFAULT_WHY.get(f, FLAG_LABELS[f])})
    for item in model_flags or []:
        if isinstance(item, str):
            item = {"flag": item, "why": ""}
        if not isinstance(item, dict):
            continue
        f = item.get("flag")
        if f not in SPIN_FLAGS or f in seen:
            continue
        seen.add(f)
        why = normalize_ws(item.get("why") or "")[:240] or FLAG_LABELS[f]
        out.append({"flag": f, "why": why})
    return out


_DEFAULT_WHY = {
    "no-study-located": "No DOI, PubMed record, or matching citation could be found for this claim.",
    "sample-under-50": "The abstract reports fewer than 50 participants.",
    "animal-or-in-vitro-reported-as-human": "The study was not in people, but the headline does not say so.",
    "preprint-unlabeled": "The paper is a preprint and the article never says so.",
    "press-release-source": "The article reads as a press release, not independent reporting.",
    "relative-only": "The abstract reports a relative effect with no baseline risk, so the absolute change is unknown.",
}


def grade(fields, flags, concordance, *, study_found=True):
    """1-5 grains of salt from the validated fields. Deterministic.

    design tier (1-4) -> +species (non-human floors at 4) -> +1 if n < 50
    -> +concordance penalty (2 faithful: 0, 1 partial: +1, 0 contradicts:
    +2, unknown: 0) -> +1 if any flag, +1 more at three or more flags.
    No study located is always 5.
    """
    if not study_found:
        return 5
    fields = fields or {}
    design = (fields.get("design") or {}).get("value")
    g = _DESIGN_TIER.get(design, 3)
    species = (fields.get("species") or {}).get("value")
    if species in ("animal", "in-vitro"):
        g = max(g, 4)
    n = (fields.get("n") or {}).get("value")
    if isinstance(n, int) and n < SMALL_SAMPLE:
        g += 1
    if concordance == 1:
        g += 1
    elif concordance == 0:
        g += 2
    keys = [f["flag"] if isinstance(f, dict) else f for f in (flags or [])]
    keys = [k for k in keys if k in SPIN_FLAGS]
    if keys:
        g += 1
    if len(keys) >= 3:
        g += 1
    return max(1, min(5, g))


def is_health_text(title, body):
    """Cheap lexicon gate: at least two distinct health-research terms in
    the title plus the first 1,500 characters of the body."""
    text = f"{title or ''} {(body or '')[:_HEALTH_HEAD_CHARS]}".lower()
    hits = 0
    for term in _HEALTH_TERMS:
        if term in text:
            hits += 1
            if hits >= _HEALTH_MIN_HITS:
                return True
    return False


def split_pasted_text(text):
    """A pasted headline + paragraph: first non-empty line is the headline,
    the rest is the body. Returns (headline, body)."""
    lines = [l.strip() for l in (text or "").splitlines()]
    lines = [l for l in lines if l]
    if not lines:
        return "", ""
    return lines[0][:300], " ".join(lines[1:])[:20000]


def citation_label(study):
    """One-line citation for the card: `First Author et al., Journal (Year)`."""
    if not study:
        return ""
    bits = []
    if study.get("first_author"):
        bits.append(f"{study['first_author']} et al.")
    if study.get("journal"):
        bits.append(study["journal"])
    label = ", ".join(bits)
    if study.get("year"):
        label = f"{label} ({study['year']})".strip()
    return label


def study_url(study):
    if not study:
        return None
    if study.get("doi"):
        return f"https://doi.org/{study['doi']}"
    if study.get("pmid"):
        return f"https://pubmed.ncbi.nlm.nih.gov/{study['pmid']}/"
    return study.get("url")
