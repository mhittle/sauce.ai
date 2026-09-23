"""Two-phase clinician review selection (RESEARCH.md §4).

Phase 1: the screener labels every output. Phase 2: select for clinician
review **all screen-positives** (inclusion probability 1) plus a **stratified
random sample of screen-negatives** at `neg_sample_rate`, stratified by pathway
× target model, recording each item's inclusion probability for the
Horvitz–Thompson estimator.

Pure selection here; DB assembly lives in the endpoint.
"""
from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class Selected:
    turn_id: int
    run_id: str
    screen_positive: bool
    inclusion_prob: float
    stratum: str
    pathway: str
    sample_source: str
    sampling_weight: float


def select_two_phase(screener_labels: list[dict], neg_sample_rate: float = 0.10,
                     seed: int = 0) -> list[Selected]:
    """screener_labels: rows from `store.che_labels(run_id, 'llm_screener')`,
    each carrying turn_id, run_id, pathway, screen_positive, sample_source,
    sampling_weight, attacker_refused. Attacker refusals are never selected."""
    rng = random.Random(seed)
    pool = [l for l in screener_labels if not l.get("attacker_refused")]
    positives = [l for l in pool if l.get("screen_positive")]
    negatives = [l for l in pool if not l.get("screen_positive")]

    out: list[Selected] = []
    for l in positives:
        out.append(_mk(l, incl=1.0))

    # stratified sample of negatives by pathway × run (one run = one target)
    strata: dict[tuple, list[dict]] = {}
    for l in negatives:
        strata.setdefault((l.get("pathway", "?"), l["run_id"]), []).append(l)
    rate = max(0.0, min(1.0, neg_sample_rate))
    for members in strata.values():
        take = int(round(len(members) * rate))
        if rate > 0 and take == 0 and members:
            take = 1  # ensure some negative coverage per stratum when sampling is on
        chosen = members[:]
        rng.shuffle(chosen)
        incl = (take / len(members)) if members else 0.0
        for l in chosen[:take]:
            out.append(_mk(l, incl=incl))
    rng.shuffle(out)
    return out


def _mk(l: dict, incl: float) -> Selected:
    return Selected(
        turn_id=l["turn_id"], run_id=l["run_id"], screen_positive=bool(l.get("screen_positive")),
        inclusion_prob=incl, stratum=f"{l.get('pathway', '?')}·{l['run_id']}",
        pathway=l.get("pathway", "other"), sample_source=l.get("sample_source", "representative"),
        sampling_weight=float(l.get("sampling_weight", 1.0)))
