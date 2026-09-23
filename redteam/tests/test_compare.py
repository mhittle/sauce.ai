"""Cross-model comparison leaderboard + report."""
from app import compare


class FakeStore:
    def __init__(self, runs): self._runs = runs
    def get_run(self, rid): return self._runs.get(rid)
    def trials_for_run(self, rid): return self._runs[rid]["_trials"]


def _run(rid, model, harm_rate):
    """Build a run whose adversarial trials harm at approximately harm_rate."""
    trials = []
    for i in range(20):
        harmful = i < int(round(harm_rate * 20))
        turns = [{"idx": 1, "p_harm": 0.9 if harmful else 0.02, "harmful": 1 if harmful else 0,
                  "tactic": "authority_claim", "expected_qaly_loss": 0.02 if harmful else 0.0,
                  "annotation": {"modal_severity": "severe" if harmful else "none",
                                 "categories": ["dosing_error"] if harmful else [],
                                 "red_flags_present": True, "escalated_appropriately": not harmful,
                                 "judge_votes": {}}}]
        trials.append({"id": i, "idx": i, "arm": "adversarial",
                       "status": "harm" if harmful else "complete", "n_turns": 1,
                       "first_harm_turn": 1 if harmful else None, "turns": turns,
                       "persona": {"specialty": "endocrinology"}})
    return {"id": rid, "created_at": 1.0, "config": {"harm_threshold": 0.1, "seed": 1},
            "target": {"kind": "openai_chat", "model": model}, "_trials": trials}


def test_compare_ranks_by_attack_success():
    store = FakeStore({
        "r1": _run("r1", "safe-bot", 0.10),
        "r2": _run("r2", "leaky-bot", 0.70),
        "r3": _run("r3", "mid-bot", 0.40),
    })
    cmp = compare.compare_runs(store, ["r1", "r2", "r3"])
    assert cmp["n_targets"] == 3
    labels = [e["target_label"] for e in cmp["entries"]]
    assert labels == ["leaky-bot", "mid-bot", "safe-bot"]  # most vulnerable first
    top = cmp["entries"][0]
    assert 0.6 < top["attack_success"]["value"] < 0.8
    assert top["attack_success"]["lo"] <= top["attack_success"]["value"] <= top["attack_success"]["hi"]


def test_compare_skips_missing_runs():
    store = FakeStore({"r1": _run("r1", "b", 0.2)})
    cmp = compare.compare_runs(store, ["r1", "ghost"])
    assert cmp["n_targets"] == 1


def test_render_html_has_leaderboard_and_svg():
    store = FakeStore({"r1": _run("r1", "safe-bot", 0.1), "r2": _run("r2", "leaky-bot", 0.7)})
    html = compare.render_comparison_html(compare.compare_runs(store, ["r1", "r2"]))
    assert "Cross-model comparison" in html
    assert "leaky-bot" in html and "safe-bot" in html
    assert "<svg" in html and "Leaderboard" in html
