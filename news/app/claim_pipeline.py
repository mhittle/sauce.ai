"""The four-stage /claim pipeline: locate -> resolve -> extract -> grade.

Flask-free orchestration so the route (now) and the nightly pre-compute
(feed-integration PR) share one engine. Every collaborator is injectable
for tests. Raises `LLMUnavailable` when a model call fails; "no study
located" is a normal result, not an error.

Result shape (also what the route persists, split across the JSON columns):

    {
      "status": "ok" | "no-study",
      "headline": str,
      "claim": {claim, claim_sentences, identifiers, source_kind, mentions_study},
      "study": {...resolver dict incl. abstract} | None,
      "fields": {validated field -> {value, span}},
      "numbers": {absolute_effect(...)},
      "flags": [{flag, why}],
      "concordance": 0|1|2|None, "concordance_why": str,
      "grade": 1..5,
      "usages": [usage, ...],
    }
"""
from . import claim
from .claim_sources import resolve_study
from .classifier.claim_llm import extract_evidence, grade_concordance, locate_claim


def run_check(*, headline, body, api_key, model_locate, model_extract,
              contact_email="", session=None,
              locate=locate_claim, resolve=resolve_study,
              extract=extract_evidence, grade=grade_concordance):
    headline = claim.normalize_ws(headline)[:300]
    body = body or ""
    usages = []

    loc = locate(api_key, model_locate, headline, body)
    usages.append(loc.get("usage"))
    ids = dict(loc.get("identifiers") or {})
    # Deterministic pre-pass: a DOI / PMID literally in the text beats
    # whatever the model transcribed.
    dois = claim.find_dois(body)
    if dois:
        ids["doi"] = dois[0]
    pmids = claim.find_pmids(body)
    if pmids and not ids.get("pmid"):
        ids["pmid"] = pmids[0]
    claim_info = {
        "claim": loc.get("claim") or headline,
        "claim_sentences": loc.get("claim_sentences") or [],
        "identifiers": ids,
        "source_kind": loc.get("source_kind") or "unknown",
        "mentions_study": bool(loc.get("mentions_study")),
    }

    study = resolve(ids, session=session, contact_email=contact_email)
    if not study:
        flags = claim.merge_flags(claim.deterministic_flags({}, study_found=False, headline=headline), [])
        return {
            "status": "no-study",
            "headline": headline,
            "claim": claim_info,
            "study": None,
            "fields": {},
            "numbers": claim.absolute_effect(None, None),
            "flags": flags,
            "concordance": None,
            "concordance_why": "",
            "grade": claim.grade({}, flags, None, study_found=False),
            "usages": [u for u in usages if u],
        }

    fields = {}
    abstract = study.get("abstract") or ""
    if abstract:
        ext = extract(api_key, model_extract, abstract,
                      title=study.get("title") or "", journal=study.get("journal") or "")
        usages.append(ext.get("usage"))
        fields = claim.validate_spans(ext.get("fields"), abstract)

    baseline = (fields.get("baseline_risk") or {}).get("value")
    numbers = claim.absolute_effect(fields.get("effect"), baseline)

    excerpt = " ".join(claim_info["claim_sentences"]) or body[:1500]
    gr = grade(api_key, model_locate, headline=headline, claim=claim_info["claim"],
               abstract=abstract, fields=fields, source_kind=claim_info["source_kind"],
               excerpt=excerpt)
    usages.append(gr.get("usage"))

    det = claim.deterministic_flags(
        fields, study_found=True, headline=headline, claim_text=claim_info["claim"],
        article_text=body, source_kind=claim_info["source_kind"],
        study_is_preprint=bool(study.get("is_preprint")))
    flags = claim.merge_flags(det, gr.get("flags"))
    return {
        "status": "ok",
        "headline": headline,
        "claim": claim_info,
        "study": study,
        "fields": fields,
        "numbers": numbers,
        "flags": flags,
        "concordance": gr.get("concordance"),
        "concordance_why": gr.get("concordance_why") or "",
        "grade": claim.grade(fields, flags, gr.get("concordance")),
        "usages": [u for u in usages if u],
    }
