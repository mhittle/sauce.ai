"""The tidy per-turn export contract (pure stdlib).

Mirrors `redteam/app/dataset.py::TURN_COLUMNS` — the response-level unit the
statistical analysis plan (RESEARCH.md §5) is written against — and validates a
loaded dataset before any model is fit, so failures are about the data, not a
NumPy traceback three layers down.
"""
from __future__ import annotations

# Columns the analysis relies on (a subset of the full export is required; the
# export may carry more, which we ignore).
OUTCOME = "harmful"                 # 0/1 — primary binary outcome (per reply)
TIME = "turn_idx"                   # 1-based prompt index within a conversation
EVENT_TRIAL = "any_harm"           # trial-level event (derived if absent)
GROUP_TARGET = "target_label"      # system under test (cluster / fixed effect)
GROUP_PERSONA = "trial_id"         # conversation id (cluster: turns within it)

FIXED_EFFECTS = ["arm", "specialty", "tactic", "persona_focus_harm"]

REQUIRED = [
    "run_id", "target_label", "arm", "trial_id", "trial_idx", "trial_status",
    "specialty", "tactic", "turn_idx", "n_turns_in_trial", "first_harm_turn",
    "p_harm", "harmful", "harm_threshold", "seed",
]

# Allowed categorical values that the models assume.
ARMS = ("adversarial", "control")
BINARY = ("harmful",)


def _is_num(x) -> bool:
    try:
        float(x)
        return True
    except (TypeError, ValueError):
        return False


def validate(rows: list[dict]) -> list[str]:
    """Return a list of human-readable problems; empty means the dataset is
    analysable. Checks presence of required columns, binary/0-1 outcome,
    numeric time, and at least one adversarial-arm row (the analysis target)."""
    problems: list[str] = []
    if not rows:
        return ["dataset is empty"]
    cols = set(rows[0].keys())
    missing = [c for c in REQUIRED if c not in cols]
    if missing:
        problems.append(f"missing required columns: {', '.join(missing)}")
        return problems  # can't check values without the columns

    bad_outcome = sum(1 for r in rows
                      if not (_is_num(r.get(OUTCOME)) and float(r.get(OUTCOME)) in (0.0, 1.0)))
    if bad_outcome:
        problems.append(f"{bad_outcome} rows have a non-binary '{OUTCOME}' value (expected 0/1)")

    bad_time = sum(1 for r in rows if not _is_num(r.get(TIME)))
    if bad_time:
        problems.append(f"{bad_time} rows have a non-numeric '{TIME}'")

    arms = {str(r.get("arm")) for r in rows}
    if "adversarial" not in arms:
        problems.append("no adversarial-arm rows — nothing to analyse")
    unknown = arms - set(ARMS)
    if unknown:
        problems.append(f"unknown arm values: {', '.join(sorted(unknown))}")

    if len({str(r.get(GROUP_TARGET)) for r in rows}) < 1:
        problems.append("no target_label values")
    return problems


def coerce(rows: list[dict]) -> list[dict]:
    """Best-effort type coercion for the columns the models use, leaving the
    rest untouched. Non-numeric cells become None rather than raising."""
    num_cols = ("turn_idx", "n_turns_in_trial", "first_harm_turn", "p_harm",
                "harmful", "harm_threshold", "seed", "trial_idx", "is_first_harm",
                "expected_qaly_loss", "n_categories", "latency_ms", "any_harm")
    out = []
    for r in rows:
        d = dict(r)
        for c in num_cols:
            if c in d:
                d[c] = float(d[c]) if _is_num(d[c]) else None
        out.append(d)
    return out
