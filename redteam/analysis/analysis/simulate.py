"""Synthetic tidy-export generator (pure stdlib).

Produces a per-turn dataset with the same columns as the service export and a
known data-generating process — target-level harm propensity, an adversarial-arm
effect, tactic effects, and conversation-level (persona) frailty — so the
confirmatory models have real signal to recover. Used by the smoke test and as a
runnable demo when no live export is available.
"""
from __future__ import annotations

import math
import random

SPECIALTIES = ["endocrinology", "cardiology", "pediatrics", "psychiatry"]
TACTICS = ["authority_claim", "crescendo", "access_barrier", "symptom_minimization"]
_TACTIC_EFFECT = {"authority_claim": 0.6, "crescendo": 0.9,
                  "access_barrier": 0.3, "symptom_minimization": 0.5}


def _logistic(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def generate(n_targets: int = 4, trials_per_target: int = 60, max_turns: int = 6,
             control_fraction: float = 0.25, seed: int = 7,
             adversarial_effect: float = 1.4) -> list[dict]:
    """Return per-turn rows. Targets differ in baseline safety; the adversarial
    arm and stronger tactics raise the per-turn harm hazard; each conversation
    carries a random frailty so turns within it are correlated."""
    rng = random.Random(seed)
    # distinct baseline log-odds per target (safest ... leakiest)
    base = {f"target-{i+1}": lo
            for i, lo in enumerate([-3.2, -2.6, -2.0, -1.4, -1.0, -0.6][:n_targets])}
    rows: list[dict] = []
    tid = 0
    for target, b0 in base.items():
        for t in range(trials_per_target):
            tid += 1
            arm = "control" if rng.random() < control_fraction else "adversarial"
            specialty = rng.choice(SPECIALTIES)
            tactic = rng.choice(TACTICS) if arm == "adversarial" else "benign_control"
            frailty = rng.gauss(0, 0.7)  # conversation-level random intercept
            arm_eff = adversarial_effect if arm == "adversarial" else 0.0
            tac_eff = _TACTIC_EFFECT.get(tactic, 0.0)
            first_harm = None
            turns = []
            for turn in range(1, max_turns + 1):
                lp = b0 + arm_eff + tac_eff + frailty + 0.15 * (turn - 1)
                p = _logistic(lp)
                harmful = 1 if rng.random() < p else 0
                turns.append((turn, p, harmful))
                if harmful and first_harm is None:
                    first_harm = turn
                    break  # stop_on_harm
            n_turns = turns[-1][0]
            for (turn, p, harmful) in turns:
                rows.append({
                    "run_id": f"run-{target}", "target_label": target, "arm": arm,
                    "trial_idx": t, "trial_id": tid,
                    "trial_status": "harm" if first_harm else "complete",
                    "specialty": specialty, "condition": "", "tactic": tactic,
                    "persona_focus_harm": "dosing_error",
                    "turn_idx": turn, "n_turns_in_trial": n_turns,
                    "first_harm_turn": first_harm if first_harm else "",
                    "is_first_harm": 1 if first_harm == turn else 0,
                    "p_harm": round(p, 4), "harmful": harmful,
                    "any_harm": 1 if first_harm else 0,
                    "harm_threshold": 0.1, "seed": seed,
                })
    rng.shuffle(rows)
    return rows
