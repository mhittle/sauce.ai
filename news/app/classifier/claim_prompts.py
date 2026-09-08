"""Prompts + JSON schemas for the three /claim model calls.

1. LOCATE (Haiku): pull the claim sentence and any study identifiers out
   of the article text. Deterministic resolvers do the actual lookup.
2. EXTRACT (Sonnet): structured evidence from the abstract, every field
   with a verbatim `span`; `app.claim.validate_spans` drops anything the
   abstract does not literally contain.
3. GRADE (Haiku): headline-vs-abstract concordance (0-2) plus spin flags
   from a closed list, one line of justification each. The model never
   emits a grade — `app.claim.grade` computes it.
"""
from ..claim import DESIGNS, EFFECT_TYPES, OUTCOME_TYPES, PEER_REVIEW, SPECIES

MAX_BODY_CHARS = 6000
MAX_ABSTRACT_CHARS = 6000

_NULLABLE_STR = {"type": ["string", "null"]}
_NULLABLE_NUM = {"type": ["number", "null"]}
_NULLABLE_INT = {"type": ["integer", "null"]}

LOCATE_SYSTEM = """You read a news article about a health or science claim and pull out
(a) the central claim as the article states it and (b) every identifier of
the underlying study the article mentions. You do not judge the claim.

Rules:
- `claim`: one sentence, the strongest health/science assertion the
  headline or lede makes, quoted or lightly trimmed from the article.
- `claim_sentences`: up to 3 verbatim sentences from the article that
  carry the claim or describe the study.
- `identifiers`: copy exactly what the article gives. DOI (10.xxxx/...),
  PMID, the paper's title if quoted, first or lead author surname,
  journal name, institution, publication year. Use null for anything the
  article does not state. Never guess a DOI or a journal.
- `mentions_study`: true only if the article refers to a specific study,
  trial, paper, or analysis (not just "experts say").
- `source_kind`: "press-release" if the text reads as an institutional
  press release (EurekAlert-style, quotes only from the authors' own
  institution, "researchers at X announced"); "blog" for a personal or
  advocacy site; "news" for independent reporting; "unknown" otherwise.

Output STRICT JSON only, no prose."""

LOCATE_SCHEMA = {
    "type": "object",
    "properties": {
        "claim": {"type": "string"},
        "claim_sentences": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "mentions_study": {"type": "boolean"},
        "identifiers": {
            "type": "object",
            "properties": {
                "doi": _NULLABLE_STR,
                "pmid": _NULLABLE_STR,
                "title": _NULLABLE_STR,
                "first_author": _NULLABLE_STR,
                "journal": _NULLABLE_STR,
                "institution": _NULLABLE_STR,
                "year": _NULLABLE_INT,
            },
            "required": ["doi", "pmid", "title", "first_author", "journal", "institution", "year"],
            "additionalProperties": False,
        },
        "source_kind": {"type": "string", "enum": ["news", "press-release", "blog", "unknown"]},
    },
    "required": ["claim", "claim_sentences", "mentions_study", "identifiers", "source_kind"],
    "additionalProperties": False,
}

LOCATE_USER_TEMPLATE = """Headline: {headline}

Article text:
{body}"""


def _span_field(value_schema):
    return {
        "type": ["object", "null"],
        "properties": {"value": value_schema, "span": {"type": "string"}},
        "required": ["value", "span"],
        "additionalProperties": False,
    }


EXTRACT_SYSTEM = f"""You are an epidemiologist extracting the evidence from one study abstract.
Every field you return MUST carry `span`: the exact, verbatim substring of
the abstract the value came from (copy it character for character). If the
abstract does not state something, return null for that field. Do not
infer, round, or compute. A field without a literal supporting span will be
discarded by a validator, so a null is always better than a guess.

Fields:
- design: one of {list(DESIGNS)}. "rct" = randomized controlled trial;
  "meta-analysis" includes systematic reviews with pooled estimates;
  "animal" / "in-vitro" when the subjects are not people.
- species: one of {list(SPECIES)}.
- n: total participants (or animals / samples) analysed, as an integer
  that appears in the span.
- population, exposure, comparator, outcome, follow_up: short phrases.
- outcome_type: one of {list(OUTCOME_TYPES)}. "hard" = death, disease
  events, hospitalisation; "surrogate" = biomarkers, imaging, scores.
- effect: the primary result. type in {list(EFFECT_TYPES)} (RR relative
  risk / rate ratio, OR odds ratio, HR hazard ratio, MD mean difference,
  other). point, ci_low, ci_high are numbers that appear verbatim in the
  span; ci fields null if no interval is given.
- baseline_risk: the control / unexposed group's absolute risk of the
  primary outcome as a proportion (0.08 for 8%). Only if the abstract
  states it; the number must appear in the span.
- funding: the funder as stated. peer_review: "preprint" if the text or
  venue says so, "peer-reviewed" if a journal is stated, else "unclear".

Output STRICT JSON only, no prose."""

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "design": _span_field({"type": "string", "enum": list(DESIGNS)}),
        "species": _span_field({"type": "string", "enum": list(SPECIES)}),
        "n": _span_field({"type": "integer"}),
        "population": _span_field({"type": "string"}),
        "exposure": _span_field({"type": "string"}),
        "comparator": _span_field({"type": "string"}),
        "outcome": _span_field({"type": "string"}),
        "outcome_type": _span_field({"type": "string", "enum": list(OUTCOME_TYPES)}),
        "follow_up": _span_field({"type": "string"}),
        "effect": {
            "type": ["object", "null"],
            "properties": {
                "type": {"type": "string", "enum": list(EFFECT_TYPES)},
                "point": {"type": "number"},
                "ci_low": _NULLABLE_NUM,
                "ci_high": _NULLABLE_NUM,
                "span": {"type": "string"},
            },
            "required": ["type", "point", "ci_low", "ci_high", "span"],
            "additionalProperties": False,
        },
        "baseline_risk": _span_field({"type": "number"}),
        "funding": _span_field({"type": "string"}),
        "peer_review": _span_field({"type": "string", "enum": list(PEER_REVIEW)}),
    },
    "required": ["design", "species", "n", "population", "exposure", "comparator",
                 "outcome", "outcome_type", "follow_up", "effect", "baseline_risk",
                 "funding", "peer_review"],
    "additionalProperties": False,
}

EXTRACT_USER_TEMPLATE = """Paper: {title}
Venue: {journal}

Abstract:
{abstract}"""

# Flags the model may select. `no-study-located` and `sample-under-50` are
# computed in code and are deliberately not offered here.
MODEL_FLAGS = (
    "causal-language-on-observational",
    "surrogate-as-hard-outcome",
    "single-study-as-consensus",
    "relative-only",
    "animal-or-in-vitro-reported-as-human",
    "preprint-unlabeled",
    "press-release-source",
)

GRADE_SYSTEM = """You compare a news headline and its central claim against the abstract of
the study it reports on. You grade the REPORTING, never the treatment, and
you give no medical advice.

Return:
- concordance: 2 if the headline/claim says what the abstract supports
  (same population, same direction, same strength of language); 1 if it
  stretches it (stronger verbs, broader population, a secondary outcome
  promoted to the headline, a surrogate framed as the disease); 0 if it
  says something the abstract does not support or contradicts it.
- concordance_why: one sentence.
- flags: zero or more from this closed list, each with a one-line `why`
  that quotes the offending wording where possible:
  causal-language-on-observational — "causes", "cuts", "prevents", "boosts"
    on a cohort / case-control / cross-sectional design.
  surrogate-as-hard-outcome — a biomarker or score reported as the disease
    or death itself.
  single-study-as-consensus — "proves", "settled", "confirms" on one study.
  relative-only — the article gives a relative change with no absolute
    numbers.
  animal-or-in-vitro-reported-as-human — the study was in animals or cells
    and the headline or claim reads as if in people.
  preprint-unlabeled — the paper is a preprint and the article never says so.
  press-release-source — the article is a press release or reproduces one.
Do not invent flags outside the list. Do not output a grade or a score.

Output STRICT JSON only, no prose."""

GRADE_SCHEMA = {
    "type": "object",
    "properties": {
        "concordance": {"type": "integer", "enum": [0, 1, 2]},
        "concordance_why": {"type": "string"},
        "flags": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "flag": {"type": "string", "enum": list(MODEL_FLAGS)},
                    "why": {"type": "string"},
                },
                "required": ["flag", "why"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["concordance", "concordance_why", "flags"],
    "additionalProperties": False,
}

GRADE_USER_TEMPLATE = """Headline: {headline}
Claim as the article states it: {claim}
Article source kind: {source_kind}

Study design (validated from the abstract): {design}
Species: {species}
Peer review status: {peer_review}

Abstract:
{abstract}

Article excerpt:
{excerpt}"""
