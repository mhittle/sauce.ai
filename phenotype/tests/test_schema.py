from app.catalog import EXEMPLAR
from app.schema import Algorithm, ExtractedAlgorithm, MetricValue, Validation


def test_untrusted_model_output_is_coerced():
    a = Algorithm.from_dict({"name": "x", "coding_era": "ICD10", "data_types": ["claims", "bogus"],
                             "rules": [{"min_events": "3", "window_days": "365.0", "components": [
                                 {"domain": "Diagnosis", "code_system": "icd10cm", "codes": ["G35", "G35", "; DROP"],
                                  "care_setting": "weird"}]}]})
    c = a.rules[0].components[0]
    assert (c.domain, c.code_system, c.care_setting) == ("diagnosis", "ICD10CM", "any")
    assert c.codes == ["G35"]
    assert a.rules[0].min_events == 3 and a.rules[0].window_days == 365
    assert a.data_types == ["claims"] and a.coding_era == "icd10"
    assert Algorithm.from_dict({"name": "no rules"}) is None


def test_metric_percentages_and_bad_ci():
    m = MetricValue.from_dict({"value": "94.2%", "lo": 91, "hi": 96})
    assert m.value == 0.942 and m.lo == 0.91
    m = MetricValue.from_dict({"value": 0.9, "lo": 0.95, "hi": 0.99})
    assert m.lo is None and m.hi is None
    m = MetricValue.from_dict({"x": 45, "n": 50})
    assert m.value == 0.9
    assert MetricValue.from_dict({"value": 3}).value == 0.03  # read as a percentage
    assert MetricValue.from_dict({"value": 300}) is None


def test_positives_only_sampling_keeps_only_ppv():
    v = Validation.from_dict({"sampling": "positives_only", "metrics": {
        "ppv": {"value": 0.95}, "sensitivity": {"value": 0.99}}})
    assert set(v.metrics) == {"ppv"}
    assert Validation.from_dict({"sampling": "positives_only", "metrics": {"sensitivity": 0.9}}) is None


def test_signature_ignores_labels_drug_lists_and_icd_detail():
    a = Algorithm.from_dict(EXEMPLAR["algorithm"])
    d = {**EXEMPLAR["algorithm"], "name": "other name"}
    d["rules"] = [{**d["rules"][0], "components": [
        {"domain": "diagnosis", "code_system": "ICD9CM", "codes": ["340.0"], "label": "x"},
        {"domain": "diagnosis", "code_system": "ICD10CM", "codes": ["G35"]},
        {"domain": "drug", "code_system": "RxNorm", "codes": ["natalizumab"]}]}]
    assert Algorithm.from_dict(d).signature() == a.signature()
    d["rules"][0]["min_events"] = 2
    assert Algorithm.from_dict(d).signature() != a.signature()


def test_extracted_requires_algorithm_and_validation():
    assert ExtractedAlgorithm.from_dict({"algorithm": EXEMPLAR["algorithm"], "validations": []}) is None
    ea = ExtractedAlgorithm.from_dict({"algorithm": EXEMPLAR["algorithm"], "role": "nonsense",
                                       "validations": [{"metrics": {"ppv": 0.95}}]})
    assert ea.role == "developed"
