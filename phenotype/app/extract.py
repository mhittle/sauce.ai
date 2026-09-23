"""Model steps: suggest known papers, screen abstracts, extract algorithms.

The model never supplies a reference: suggestions are resolved against
PubMed or dropped, and every extracted accuracy metric must carry a quote
that appears verbatim in the text the model was given and contains the
number. Metrics that fail are kept but marked unverified, which the grader
penalizes.
"""
from __future__ import annotations

import json
import re

from . import catalog as C
from .providers import ChatModel, ModelError, chat_json
from .schema import ExtractedAlgorithm, Study

SUGGEST_SYSTEM = """You are an epidemiologist who specializes in computable phenotypes and validation of case-ascertainment algorithms in administrative claims, EHR and registry data.
List published studies that DEVELOP or VALIDATE an algorithm (case definition) for identifying the condition, and report accuracy against a reference standard (chart review, registry, clinical exam).
Only list papers you are confident exist. Give the exact title as published. Reply with JSON only:
{"papers": [{"title": "...", "first_author": "...", "year": 2019}]}"""

SCREEN_SYSTEM = """You screen bibliographic records for a review of validated case-ascertainment (phenotyping) algorithms.
Classify each record:
- "validation": a primary study that develops or validates an algorithm / case definition for identifying the TARGET CONDITION in administrative claims, EHR, or registry data AND reports at least one accuracy measure (sensitivity, specificity, PPV, NPV) against a reference standard.
- "review": a systematic or narrative review of such algorithms for the target condition (useful for snowballing).
- "exclude": anything else (applies an algorithm without validating it, different condition, clinical diagnostic test accuracy, methods only).
Reply with JSON only: {"decisions": [{"id": 0, "label": "validation|review|exclude", "reason": "<= 15 words"}]}"""

EXTRACT_SYSTEM = f"""You extract phenotyping algorithms and their validation results from a research paper into a strict JSON schema, for an evidence review that ranks algorithms by validity.

Rules:
- Extract every distinct algorithm the paper reports accuracy for (a paper often compares several: e.g. ">=1 inpatient OR >=2 outpatient claims" vs ">=3 claims in 1 year"). Keep at most the 6 best-reported.
- One validation object per dataset / site / population the algorithm was tested in. Mark external=true when tested in data other than where it was developed.
- Proportions are decimals in [0,1] (94.2% -> 0.942). Give 95% CI bounds (lo, hi) and 2x2 counts (x = numerator, n = denominator) only when reported.
- For each metric, "quote" MUST be copied character-for-character from the paper text and contain the number. If you cannot quote it, omit the metric.
- Codes: copy the codes the paper states. If the paper names a code family without listing codes (e.g. "ICD-10 code for MS"), you may fill the standard code(s) and set "codes_source": "inferred". Never invent drug lists or codes you are unsure of: leave codes [] and describe in "label".
- A rule counts qualifying events pooled across its components: >= min_events on distinct days within window_days (null = any time); min_separation_days between first and last; require_each = every component must occur. Rules within an algorithm are OR-ed. Express "A AND B" as one rule with require_each=true, min_events=2.
- Vocabularies:
  domain: {list(C.DOMAINS)}
  code_system: {list(C.CODE_SYSTEMS)} (drugs by ingredient name -> "RxNorm")
  care_setting: {list(C.CARE_SETTINGS)}
  data_types / data_type: {list(C.DATA_TYPES)}
  coding_era: {list(C.CODING_ERAS)}
  reference_standard: {list(C.REFERENCE_STANDARDS)}
  sampling: {list(C.SAMPLING)} (positives_only = only algorithm-positive records were verified, so only PPV is valid)
  role: developed | validated_existing | applied_only
- If the paper reports no algorithm with accuracy results, reply {{"algorithms": []}}.

Worked example of the algorithm structure (the case definition validated by the US MS Prevalence Working Group, {C.EXEMPLAR['citation']}):
{json.dumps(C.EXEMPLAR['algorithm'], indent=1)}

Reply with JSON only:
{{"algorithms": [{{"role": "...", "algorithm": {{...as in the example...}},
  "validations": [{{"dataset": "", "country": "", "data_type": "", "years": "", "population": "", "n_validated": 0,
    "reference_standard": "", "reference_detail": "", "sampling": "", "blinded": null, "external": false,
    "metrics": {{"sensitivity": {{"value": 0.0, "lo": null, "hi": null, "x": null, "n": null, "quote": ""}},
                "specificity": {{}}, "ppv": {{}}, "npv": {{}}}}}}]}}]}}"""


def suggest_titles(model: ChatModel, condition: str, notes: str = "") -> list[str]:
    try:
        data = chat_json(model, SUGGEST_SYSTEM, [{"role": "user", "content":
                         f"Condition: {condition}\n{('Context: ' + notes) if notes else ''}\nList up to 15 papers."}],
                         max_tokens=3000)
    except (ModelError, ValueError):
        return []
    papers = data.get("papers") if isinstance(data, dict) else None
    return [str(p["title"])[:300] for p in (papers or []) if isinstance(p, dict) and p.get("title")][:15]


def screen(model: ChatModel, condition: str, studies: list[Study], batch: int = 12) -> dict[str, dict]:
    """{study.key: {"label", "reason"}}; records the model fails on are kept
    as "validation" (screening errs toward inclusion)."""
    out: dict[str, dict] = {}
    for i in range(0, len(studies), batch):
        chunk = studies[i:i + batch]
        listing = "\n\n".join(f"[{j}] {s.title}\n{(s.abstract or '(no abstract)')[:2500]}"
                              for j, s in enumerate(chunk))
        try:
            data = chat_json(model, SCREEN_SYSTEM, [{"role": "user", "content":
                             f"TARGET CONDITION: {condition}\n\nRECORDS:\n{listing}"}], max_tokens=3000)
            decisions = {int(d["id"]): d for d in (data.get("decisions") or []) if isinstance(d, dict) and "id" in d}
        except (ModelError, ValueError, TypeError, KeyError, AttributeError):
            decisions = {}
        for j, s in enumerate(chunk):
            d = decisions.get(j)
            label = d.get("label") if d else None
            if label not in ("validation", "review", "exclude"):
                out[s.key] = {"label": "validation", "reason": "screening failed; kept for extraction"}
            else:
                out[s.key] = {"label": label, "reason": str(d.get("reason", ""))[:200]}
    return out


def _norm(t: str) -> str:
    t = t.lower().replace("–", "-").replace("—", "-").replace("−", "-")
    t = t.replace("·", ".").replace(" ", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", t).strip()


def _number_forms(m) -> set[str]:
    """Ways the number can be written: 94, 94.2, 94.20, 0.94, .942, x counts."""
    forms: set[str] = set()
    if m.value is not None:
        pct = m.value * 100
        forms |= {f"{pct:.0f}", f"{pct:.1f}", f"{pct:.2f}"}
        for d in (2, 3):
            dec = f"{m.value:.{d}f}"
            forms |= {dec, dec.lstrip("0")}
    if m.x is not None and m.n:
        forms.add(str(m.x))
    return forms


def verify_quotes(ea: ExtractedAlgorithm, source_text: str) -> None:
    src = _norm(source_text)
    for v in ea.validations:
        for m in v.metrics.values():
            q = _norm(m.quote)
            m.verified = bool(q) and len(q) >= 6 and q in src and any(f in q for f in _number_forms(m))


def extract(model: ChatModel, condition: str, study: Study, text: str) -> list[ExtractedAlgorithm]:
    header = f"TARGET CONDITION: {condition}\nTITLE: {study.title}\nJOURNAL: {study.journal} {study.year or ''}\n"
    data = chat_json(model, EXTRACT_SYSTEM, [{"role": "user", "content":
                     header + f"\nPAPER TEXT ({study.text_basis}):\n" + text}], max_tokens=16000)
    items = data.get("algorithms") if isinstance(data, dict) else None
    out = []
    for d in (items or [])[:6]:
        ea = ExtractedAlgorithm.from_dict(d)
        if ea and ea.role != "applied_only":
            verify_quotes(ea, text)
            out.append(ea)
    return out
