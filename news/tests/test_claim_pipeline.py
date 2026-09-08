"""Orchestration tests for app.claim_pipeline with every collaborator stubbed."""
import pytest

from app import claim
from app.claim_pipeline import run_check
from app.classifier import LLMUnavailable

ABSTRACT = ("Prospective cohort of 12,000 adults. Coffee intake was associated with lower "
            "dementia incidence (hazard ratio 0.71, 95% CI 0.60 to 0.84). Dementia occurred "
            "in 6.0% of non-drinkers.")

BODY = ("Coffee cuts dementia risk, study finds. Researchers at Example University "
        "published the analysis in JAMA Neurology (doi:10.1001/jamaneurol.2024.1234).")


def _locate(api_key, model, headline, body):
    return {"claim": "Coffee cuts dementia risk by 30%", "claim_sentences": ["Coffee cuts dementia risk, study finds."],
            "mentions_study": True,
            "identifiers": {"doi": None, "pmid": None, "title": None, "first_author": None,
                            "journal": "JAMA Neurology", "institution": None, "year": 2024},
            "source_kind": "news", "usage": {"model": model, "input_tokens": 1, "output_tokens": 1,
                                             "cache_read_tokens": 0, "est_cost_usd": 0.001}}


def _extract(api_key, model, abstract, *, title="", journal=""):
    return {"fields": {
        "design": {"value": "cohort", "span": "Prospective cohort"},
        "species": {"value": "human", "span": "12,000 adults"},
        "n": {"value": 12000, "span": "12,000 adults"},
        "effect": {"type": "HR", "point": 0.71, "ci_low": 0.60, "ci_high": 0.84,
                   "span": "hazard ratio 0.71, 95% CI 0.60 to 0.84"},
        "baseline_risk": {"value": 0.06, "span": "6.0% of non-drinkers"},
        "outcome": {"value": "dementia", "span": "NOT IN ABSTRACT"},
    }, "usage": {"model": model, "input_tokens": 2, "output_tokens": 2, "cache_read_tokens": 0, "est_cost_usd": 0.002}}


def _grade(api_key, model, **kw):
    return {"concordance": 1, "concordance_why": "'cuts' on a cohort.",
            "flags": [{"flag": "causal-language-on-observational", "why": "'cuts'"}],
            "usage": {"model": model, "input_tokens": 3, "output_tokens": 3, "cache_read_tokens": 0, "est_cost_usd": 0.003}}


def _resolve_found(ids, *, session=None, contact_email=""):
    assert ids["doi"] == "10.1001/jamaneurol.2024.1234"
    return {"doi": ids["doi"], "pmid": None, "title": "Coffee and dementia", "journal": "JAMA Neurology",
            "year": 2024, "first_author": "Lee", "authors": ["Lee"], "abstract": ABSTRACT,
            "is_preprint": False, "resolver": "crossref+europepmc", "url": None, "publication_types": []}


def test_happy_path_end_to_end():
    out = run_check(headline="Coffee cuts dementia risk", body=BODY, api_key="k",
                    model_locate="haiku", model_extract="sonnet",
                    locate=_locate, resolve=_resolve_found, extract=_extract, grade=_grade)
    assert out["status"] == "ok"
    # regex DOI pre-pass overrode the model's null
    assert out["claim"]["identifiers"]["doi"] == "10.1001/jamaneurol.2024.1234"
    assert set(out["fields"]) == {"design", "species", "n", "effect", "baseline_risk"}
    assert out["numbers"]["arr_pct"] == pytest.approx(1.7, abs=0.05)
    assert out["numbers"]["nnt"] == 57
    assert [f["flag"] for f in out["flags"]] == ["causal-language-on-observational"]
    assert out["concordance"] == 1
    # cohort (2) + concordance 1 (+1) + a flag (+1) = 4
    assert out["grade"] == 4
    assert [u["model"] for u in out["usages"]] == ["haiku", "sonnet", "haiku"]


def test_no_study_short_circuits_before_extract_and_grade():
    def boom(*a, **k):
        raise AssertionError("should not be called")
    out = run_check(headline="Chocolate cures cancer", body="No citation here.", api_key="k",
                    model_locate="h", model_extract="s",
                    locate=_locate, resolve=lambda ids, **k: None, extract=boom, grade=boom)
    assert out["status"] == "no-study"
    assert out["grade"] == 5
    assert [f["flag"] for f in out["flags"]] == ["no-study-located"]
    assert out["numbers"]["baseline_missing"] is True
    assert len(out["usages"]) == 1


def test_study_without_abstract_skips_extract_but_still_grades():
    def resolve(ids, **k):
        return {"doi": "10.1/x", "title": "T", "journal": "J", "year": 2020, "first_author": "A",
                "abstract": None, "is_preprint": True, "resolver": "crossref"}
    def boom(*a, **k):
        raise AssertionError("no abstract -> no extract call")
    out = run_check(headline="h", body="body with doi:10.1000/abc", api_key="k",
                    model_locate="h", model_extract="s",
                    locate=_locate, resolve=resolve, extract=boom, grade=_grade)
    assert out["fields"] == {}
    assert out["numbers"]["type"] is None
    flags = [f["flag"] for f in out["flags"]]
    assert "preprint-unlabeled" in flags and "causal-language-on-observational" in flags
    # unknown design (3) + concordance 1 (+1) + flags (+1) = 5
    assert out["grade"] == 5


def test_llm_unavailable_propagates():
    def locate(*a, **k):
        raise LLMUnavailable("nope")
    with pytest.raises(LLMUnavailable):
        run_check(headline="h", body="b", api_key="k", model_locate="h", model_extract="s", locate=locate)


def test_grade_is_never_taken_from_the_model():
    def grade(api_key, model, **kw):
        return {"concordance": 2, "concordance_why": "", "flags": [], "grade": 1,
                "usage": None}
    out = run_check(headline="Coffee", body=BODY, api_key="k", model_locate="h", model_extract="s",
                    locate=_locate, resolve=_resolve_found, extract=_extract, grade=grade)
    assert out["grade"] == claim.grade(out["fields"], [], 2) == 2
