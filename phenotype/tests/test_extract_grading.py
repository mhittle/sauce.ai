import json

from app.catalog import EXEMPLAR
from app.extract import extract, screen, suggest_titles, verify_quotes
from app.grading import Context, rank, validation_risk
from app.providers import MockModel
from app.schema import ExtractedAlgorithm, Study, Validation
from tests.fakes import ARTICLES, FULLTEXT, ONE_CLAIM, extract_responder, screen_responder


def study(key, title="t"):
    return Study(key=key, title=title, pmid=key.split(":")[-1])


def test_quote_verification():
    ea = ExtractedAlgorithm.from_dict({"algorithm": EXEMPLAR["algorithm"], "validations": [{"metrics": {
        "sensitivity": {"value": 0.921, "quote": "sensitivity  of 92.1% (95% CI 88.0–95.0)"},
        "ppv": {"value": 0.96, "quote": "PPV of 99.0%"},
        "specificity": {"value": 0.9, "quote": "specificity of 90%"}}}]})
    verify_quotes(ea, "... had a sensitivity of 92.1% (95% CI 88.0-95.0) and a PPV of 96.0% ...")
    m = ea.validations[0].metrics
    assert m["sensitivity"].verified          # whitespace + dash normalized
    assert not m["ppv"].verified              # quote not in the source
    assert not m["specificity"].verified


def test_extract_with_mock_marks_verified():
    s = study("pmid:111", ARTICLES["111"]["title"])
    s.text_basis = "full text"
    model = MockModel("x", extract_responder)
    [ea] = extract(model, "multiple sclerosis", s, FULLTEXT)
    assert ea.algorithm.rules[0].min_events == 3
    assert all(m.verified for m in ea.validations[0].metrics.values())


def test_extract_drops_applied_only_and_bad_json_raises():
    applied = MockModel("a", lambda s, m: json.dumps({"algorithms": [
        {"role": "applied_only", "algorithm": EXEMPLAR["algorithm"], "validations": [{"metrics": {"ppv": 0.9}}]}]}))
    assert extract(applied, "ms", study("pmid:1"), "x") == []


def test_screen_labels_and_failure_keeps_record():
    recs = [study("pmid:1", "Validation of X"), study("pmid:2", "A review of Y"), study("pmid:3", "Costs")]
    out = screen(MockModel("s", screen_responder), "x", recs)
    assert [out[r.key]["label"] for r in recs] == ["validation", "review", "exclude"]
    broken = screen(MockModel("b", lambda s, m: "not json"), "x", recs)
    assert all(v["label"] == "validation" for v in broken.values())


def test_suggest_titles_survives_garbage():
    assert suggest_titles(MockModel("g", lambda s, m: "nope"), "x") == []


def test_risk_of_bias_domains():
    v = Validation.from_dict({"reference_standard": "chart_review_criteria", "sampling": "population_random",
                              "blinded": True, "metrics": {"ppv": 0.9}})
    assert validation_risk(v)["overall"] == "low"
    v.sampling = "case_control"
    assert validation_risk(v)["overall"] == "high"
    v.sampling, v.blinded = "population_random", None
    assert validation_risk(v)["overall"] == "unclear"


def _studies():
    a = study("pmid:111")
    a.algorithms = [ExtractedAlgorithm.from_dict(json.loads(extract_responder("", [{"content":
        "Validation of an algorithm for identifying MS"}]))["algorithms"][0])]
    b = study("pmid:222")
    b.algorithms = [ExtractedAlgorithm.from_dict(d) for d in
                    json.loads(extract_responder("", [{"content": "Manitoba"}]))["algorithms"]]
    for s in (a, b):
        for ea in s.algorithms:
            for v in ea.validations:
                for m in v.metrics.values():
                    m.verified = "99%" not in m.quote   # the one-claim PPV quote is "fabricated"
    return [a, b]


def test_rank_pools_same_algorithm_across_studies_and_prefers_it():
    cands = rank(_studies(), Context("prevalence", ["claims"], "icd10", "United States", 0.003))
    top = cands[0]
    assert top.algorithm.name == EXEMPLAR["algorithm"]["name"]
    assert top.pooled["sensitivity"]["k"] == 2
    assert 0.88 < top.pooled["sensitivity"]["value"] < 0.93
    assert top.at_prevalence and 0 < top.at_prevalence["ppv"] < 1
    assert top.grade["level"] >= 2
    weak = cands[1]
    assert weak.algorithm.name == ONE_CLAIM["name"]
    assert weak.pooled["ppv"]["verified"] is False
    assert any("extraction" in r for r in weak.grade["reasons"])
    assert weak.grade["level"] == 1


def test_intended_use_changes_ranking_inputs():
    prev = rank(_studies(), Context("prevalence"))[0]
    find = rank(_studies(), Context("case_finding"))[0]
    assert prev.accuracy != find.accuracy


def test_applicability_penalties():
    s = _studies()
    notes = rank(s, Context("prevalence", ["ehr_notes"], "icd10", "Germany"))[0].applicability_notes
    assert any("your data is ehr_notes" in n for n in notes)
    assert any("not Germany" in n for n in notes)
