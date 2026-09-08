"""Pure tests for app.claim: spans, effect math, rubric, lexicon, citations."""
import pytest

from app import claim

ABSTRACT = (
    "Background: We conducted a randomized controlled trial of daily aspirin "
    "in 1,204 adults aged 50-70 with no prior cardiovascular disease. "
    "Methods: Participants were assigned to aspirin or placebo and followed "
    "for a median of 4.7 years. The primary outcome was myocardial infarction. "
    "Results: Aspirin reduced the risk of myocardial infarction (relative risk "
    "0.62, 95% CI 0.48 to 0.81). The event rate in the placebo group was 8.0%. "
    "Funding: National Heart Foundation. Conclusions: Aspirin lowers MI risk."
)


def _field(value, span):
    return {"value": value, "span": span}


# --- citation normalization ---------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("10.1056/NEJMoa2034577", "10.1056/nejmoa2034577"),
    ("https://doi.org/10.1056/NEJMoa2034577", "10.1056/nejmoa2034577"),
    ("doi: 10.1001/jama.2020.1234.", "10.1001/jama.2020.1234"),
    ("http://dx.doi.org/10.1136/bmj.n71)", "10.1136/bmj.n71"),
    ("not a doi", None),
    ("", None),
    (None, None),
])
def test_normalize_doi(raw, expected):
    assert claim.normalize_doi(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("12345678", "12345678"),
    ("PMID: 12345678", "12345678"),
    (12345678, "12345678"),
    ("abc", None),
    ("10.1000/x", None),
    (None, None),
])
def test_normalize_pmid(raw, expected):
    assert claim.normalize_pmid(raw) == expected


def test_find_dois_and_pmids_in_prose():
    text = ("The study (doi:10.1016/S0140-6736(20)30183-5) and a second one "
            "https://doi.org/10.1001/jama.2020.1234, see PMID: 31234567.")
    assert claim.find_dois(text) == ["10.1016/s0140-6736(20)30183-5",
                                     "10.1001/jama.2020.1234"]
    assert claim.find_pmids(text) == ["31234567"]


def test_url_hash_strips_tracking_and_fragment():
    a = claim.url_hash("https://Example.com/story?utm_source=x#top")
    b = claim.url_hash("https://example.com/story/")
    assert a == b
    assert a != claim.url_hash("https://example.com/other")


# --- span validation ----------------------------------------------------

def test_span_in_text_is_whitespace_and_case_insensitive():
    assert claim.span_in_text("Relative Risk\n0.62", ABSTRACT)
    assert not claim.span_in_text("relative risk 0.72", ABSTRACT)
    assert not claim.span_in_text("", ABSTRACT)


def test_validate_spans_keeps_found_and_drops_unfound():
    fields = {
        "design": _field("RCT", "randomized controlled trial"),
        "n": _field(1204, "in 1,204 adults"),
        "population": _field("adults aged 50-70", "adults aged 50-70 with no prior cardiovascular disease"),
        "outcome": _field("myocardial infarction", "The primary outcome was stroke"),
        "funding": _field("National Heart Foundation", "Funding: National Heart Foundation"),
        "baseline_risk": _field("8%", "event rate in the placebo group was 8.0%"),
        "effect": {"type": "rr", "point": 0.62, "ci_low": 0.48, "ci_high": 0.81,
                   "span": "relative risk 0.62, 95% CI 0.48 to 0.81"},
    }
    out = claim.validate_spans(fields, ABSTRACT)
    assert out["design"]["value"] == "rct"
    assert out["n"]["value"] == 1204
    assert "population" in out
    assert "outcome" not in out
    assert out["baseline_risk"]["value"] == pytest.approx(0.08)
    assert out["effect"] == {
        "type": "RR", "point": 0.62, "ci_low": 0.48, "ci_high": 0.81,
        "span": "relative risk 0.62, 95% CI 0.48 to 0.81",
    }


def test_validate_spans_drops_number_not_in_its_span():
    fields = {
        "n": _field(2000, "in 1,204 adults"),
        "effect": {"type": "RR", "point": 0.55, "span": "relative risk 0.62"},
    }
    assert claim.validate_spans(fields, ABSTRACT) == {}


def test_validate_spans_drops_half_ci_and_bad_enum():
    fields = {
        "design": _field("quasi-experimental", "randomized controlled trial"),
        "effect": {"type": "RR", "point": 0.62, "ci_low": 0.48, "ci_high": 0.99,
                   "span": "relative risk 0.62, 95% CI 0.48 to 0.81"},
    }
    out = claim.validate_spans(fields, ABSTRACT)
    assert "design" not in out
    assert out["effect"]["ci_low"] is None and out["effect"]["ci_high"] is None


def test_validate_spans_tolerates_garbage():
    assert claim.validate_spans(None, ABSTRACT) == {}
    assert claim.validate_spans({"n": "12"}, ABSTRACT) == {}
    assert claim.validate_spans({"n": _field("x", "in 1,204 adults")}, ABSTRACT) == {}
    assert claim.validate_spans({}, "") == {}


# --- effect math --------------------------------------------------------

def test_absolute_effect_rr_with_baseline():
    out = claim.absolute_effect(
        {"type": "RR", "point": 0.62, "ci_low": 0.48, "ci_high": 0.81}, 0.08)
    assert out["baseline_missing"] is False
    assert out["baseline_pct"] == 8.0
    assert out["treated_pct"] == pytest.approx(5.0, abs=0.05)
    assert out["arr_pct"] == pytest.approx(3.0, abs=0.05)
    assert out["direction"] == "fewer"
    assert out["nnt_kind"] == "NNT"
    assert out["nnt"] == 33
    assert out["icon_control"] == 8 and out["icon_treated"] == 5
    assert out["arr_ci_low_pct"] == pytest.approx(1.5, abs=0.05)
    assert out["arr_ci_high_pct"] == pytest.approx(4.2, abs=0.05)


def test_absolute_effect_harm_direction():
    out = claim.absolute_effect({"type": "RR", "point": 1.5}, 0.10)
    assert out["direction"] == "more"
    assert out["nnt_kind"] == "NNH"
    assert out["nnt"] == 20
    assert out["icon_treated"] == 15


def test_absolute_effect_missing_baseline_never_invents():
    out = claim.absolute_effect({"type": "RR", "point": 0.62}, None)
    assert out["baseline_missing"] is True
    assert out["point"] == 0.62
    assert out["arr_pct"] is None and out["nnt"] is None
    assert out["icon_control"] is None
    assert any("no baseline" in n for n in out["notes"])


def test_absolute_effect_or_converts_below_ten_percent():
    out = claim.absolute_effect({"type": "OR", "point": 0.5}, 0.05)
    assert out["converted_from_or"] is True
    # RR = 0.5 / (0.95 + 0.05*0.5) = 0.5128 -> treated 2.56%
    assert out["treated_pct"] == pytest.approx(2.6, abs=0.05)


def test_absolute_effect_or_refuses_above_ten_percent():
    out = claim.absolute_effect({"type": "OR", "point": 0.5}, 0.30)
    assert out["converted_from_or"] is False
    assert out["arr_pct"] is None
    assert any("over 10%" in n for n in out["notes"])


def test_absolute_effect_hr_notes_approximation():
    out = claim.absolute_effect({"type": "HR", "point": 0.8}, 0.2)
    assert out["arr_pct"] == 4.0
    assert any("Hazard ratio" in n for n in out["notes"])


def test_absolute_effect_mean_difference_has_no_translation():
    out = claim.absolute_effect({"type": "MD", "point": -2.3}, 0.2)
    assert out["arr_pct"] is None
    assert out["point"] == -2.3


def test_absolute_effect_empty():
    out = claim.absolute_effect(None, None)
    assert out["type"] is None and out["baseline_missing"] is True


# --- flags --------------------------------------------------------------

def test_deterministic_flags_no_study():
    assert claim.deterministic_flags({}, study_found=False, headline="x") == ["no-study-located"]


def test_deterministic_flags_small_sample_and_animal():
    fields = {"n": _field(24, "24 mice"), "species": _field("animal", "mice"),
              "effect": {"type": "RR", "point": 0.5}}
    flags = claim.deterministic_flags(
        fields, study_found=True, headline="Coffee cuts cancer risk in half")
    assert flags == ["sample-under-50", "animal-or-in-vitro-reported-as-human", "relative-only"]
    flags = claim.deterministic_flags(
        fields, study_found=True, headline="Coffee cuts cancer risk in mice")
    assert "animal-or-in-vitro-reported-as-human" not in flags


def test_deterministic_flags_preprint_and_press_release():
    fields = {"peer_review": _field("preprint", "medRxiv")}
    flags = claim.deterministic_flags(
        fields, study_found=True, headline="h", article_text="A new study says",
        source_kind="press-release")
    assert flags == ["preprint-unlabeled", "press-release-source"]
    flags = claim.deterministic_flags(
        fields, study_found=True, headline="h",
        article_text="The preprint, not yet peer reviewed, says")
    assert flags == []


def test_merge_flags_restricts_to_closed_list_and_dedupes():
    out = claim.merge_flags(
        ["sample-under-50", "bogus"],
        [{"flag": "sample-under-50", "why": "dup"},
         {"flag": "causal-language-on-observational", "why": "  says 'causes'  "},
         {"flag": "made-up", "why": "x"}, "surrogate-as-hard-outcome", 42],
    )
    assert [f["flag"] for f in out] == [
        "sample-under-50", "causal-language-on-observational", "surrogate-as-hard-outcome"]
    assert out[1]["why"] == "says 'causes'"
    assert out[2]["why"] == claim.FLAG_LABELS["surrogate-as-hard-outcome"]


# --- rubric -------------------------------------------------------------

@pytest.mark.parametrize("design,species,n,conc,flags,expected", [
    ("rct", "human", 1204, 2, [], 1),
    ("meta-analysis", "human", 50000, 2, [], 1),
    ("rct", "human", 1204, 1, [], 2),
    ("rct", "human", 30, 2, [], 3),          # +1 small, +1 flag
    ("cohort", "human", 5000, 2, [], 2),
    ("cohort", "human", 5000, 0, [], 4),
    ("cohort", "human", 5000, 2, ["causal-language-on-observational"], 3),
    ("cross-sectional", "human", 900, 2, [], 3),
    ("animal", "animal", 40, 2, [], 5),      # 4 +1 small +1 flag -> clamp
    ("rct", "animal", 200, 2, [], 4),
    ("other", "human", None, None, [], 3),
    (None, None, None, None, [], 3),
    ("rct", "human", 1204, 2, ["a", "b", "c"], 1),  # unknown flags ignored
    ("cohort", "human", 5000, 1, ["relative-only", "causal-language-on-observational",
                                  "single-study-as-consensus"], 5),
])
def test_grade_table(design, species, n, conc, flags, expected):
    fields = {}
    if design:
        fields["design"] = _field(design, "x")
    if species:
        fields["species"] = _field(species, "x")
    if n is not None:
        fields["n"] = _field(n, "x")
    small = n is not None and n < 50
    flag_objs = [{"flag": f, "why": ""} for f in flags]
    if small and not any(f["flag"] == "sample-under-50" for f in flag_objs):
        flag_objs.append({"flag": "sample-under-50", "why": ""})
    assert claim.grade(fields, flag_objs, conc) == expected


def test_grade_no_study_is_five():
    assert claim.grade({"design": _field("rct", "x")}, [], 2, study_found=False) == 5


# --- lexicon / misc -----------------------------------------------------

def test_is_health_text_gate():
    assert claim.is_health_text(
        "Daily coffee linked to lower dementia risk, study finds", "Researchers followed 5,000 patients")
    assert not claim.is_health_text("Fed holds rates steady", "Markets rallied on the news.")
    assert not claim.is_health_text("", "")


def test_split_pasted_text():
    head, body = claim.split_pasted_text("  Coffee cures cancer \n\nA study of 10 mice...\nmore")
    assert head == "Coffee cures cancer"
    assert body == "A study of 10 mice... more"
    assert claim.split_pasted_text("") == ("", "")


def test_citation_label_and_url():
    study = {"first_author": "Smith", "journal": "BMJ", "year": 2024, "doi": "10.1136/bmj.n71"}
    assert claim.citation_label(study) == "Smith et al., BMJ (2024)"
    assert claim.study_url(study) == "https://doi.org/10.1136/bmj.n71"
    assert claim.study_url({"pmid": "123"}) == "https://pubmed.ncbi.nlm.nih.gov/123/"
    assert claim.citation_label(None) == ""
