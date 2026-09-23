"""CHE persistence + two-phase selection."""
import random

from app import che_review
from app.store import Store


def _label(turn_id, run_id, pathway, screen_positive, che=False, refused=False):
    return {"run_id": run_id, "turn_id": turn_id, "trial_id": 1, "rater_type": "llm_screener",
            "rater_id": "mock:scr", "severity": 5 if che else 1, "life_threatening": che,
            "likelihood": "high" if che else "low", "actionable": che, "pathway": pathway,
            "che": che, "rationale": "x", "model_versions": {"screener": "mock:scr"},
            "sample_source": "representative", "sampling_weight": 1.0, "turn_index": 1,
            "attacker_refused": refused, "inclusion_prob": 1.0, "screen_positive": screen_positive}


def test_che_label_upsert_and_fetch():
    s = Store(":memory:")
    s.upsert_che_label(_label(10, "r1", "dosing_toxicity", True, che=True))
    s.upsert_che_label(_label(10, "r1", "dosing_toxicity", True, che=True))  # upsert, no dup
    labels = s.che_labels("r1")
    assert len(labels) == 1 and labels[0]["che"] is True
    assert labels[0]["model_versions"]["screener"] == "mock:scr"
    assert labels[0]["screen_positive"] is True


def test_che_label_separate_raters():
    s = Store(":memory:")
    s.upsert_che_label(_label(10, "r1", "dosing_toxicity", True, che=True))
    clin = _label(10, "r1", "dosing_toxicity", None, che=True)
    clin["rater_type"] = "clinician_1"; clin["rater_id"] = "AB"
    s.upsert_che_label(clin)
    assert len(s.che_labels("r1")) == 2
    assert len(s.che_labels("r1", rater_type="clinician_1")) == 1


def test_select_two_phase_positives_certain_negatives_sampled():
    labels = [_label(i, "r1", "dosing_toxicity", screen_positive=(i < 5), che=(i < 5))
              for i in range(105)]
    sel = che_review.select_two_phase(labels, neg_sample_rate=0.10, seed=1)
    pos = [x for x in sel if x.screen_positive]
    neg = [x for x in sel if not x.screen_positive]
    assert len(pos) == 5 and all(x.inclusion_prob == 1.0 for x in pos)
    # 100 negatives in one stratum, 10% -> 10 sampled at incl_prob 0.1
    assert len(neg) == 10 and all(abs(x.inclusion_prob - 0.1) < 1e-9 for x in neg)


def test_select_two_phase_excludes_attacker_refusals():
    labels = [_label(1, "r1", "other", screen_positive=True, che=True),
              _label(2, "r1", "other", screen_positive=True, che=True, refused=True)]
    sel = che_review.select_two_phase(labels, seed=1)
    assert [x.turn_id for x in sel] == [1]


def test_select_two_phase_deterministic():
    labels = [_label(i, "r1", "dosing_toxicity", screen_positive=False) for i in range(50)]
    a = che_review.select_two_phase(labels, 0.2, seed=7)
    b = che_review.select_two_phase(labels, 0.2, seed=7)
    assert [x.turn_id for x in a] == [x.turn_id for x in b]


def test_che_review_set_roundtrip_and_blinding():
    s = Store(":memory:")
    items = [{"turn_id": 1, "run_id": "r1", "pathway": "dosing_toxicity", "screen_positive": True,
              "inclusion_prob": 1.0, "sample_source": "representative", "sampling_weight": 1.0,
              "context": {"reply": "double dose", "persona_brief": "x"}}]
    set_id = s.create_che_review_set("t", {"neg_sample_rate": 0.1}, ["r1"], items)
    blind = s.che_review_items(set_id, blinded=True)
    assert blind[0]["context"]["reply"] == "double dose"  # clinician sees the reply
    assert "pathway" not in blind[0] and "screen_positive" not in blind[0]  # but not the screener verdict
    full = s.che_review_items(set_id, blinded=False)
    assert full[0]["pathway"] == "dosing_toxicity"
