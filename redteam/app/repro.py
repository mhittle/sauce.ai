"""Reproducibility capsule: a content-addressed run manifest, a determinism
check, and a self-contained capsule.

Every run gets a **manifest** — the exact, secret-free configuration needed to
reproduce it (target identity, run config, model specs, code version, seed) —
plus a **config hash** (sha256 of the canonical manifest) that is stable across
identical configurations. A **verify** step recomputes the persona case-mix from
the manifest and checks it matches the run's actual personas, so "reproducible"
is demonstrated, not asserted. The **capsule** bundles the manifest, the
headline results, and the trial-level rows into one record a reviewer can keep.

Pure stdlib; target credentials never appear (the manifest hashes only the
secret-free target record).
"""
from __future__ import annotations

import hashlib
import json
import os
import random

from . import dataset
from .personas import make_persona
from .runner import allocate_arms

CODE_VERSION = os.environ.get("REDTEAM_GIT_SHA", "dev")

# config fields that define the experiment (everything else is incidental)
_CONFIG_KEYS = ("specialty", "condition", "focus_harms", "n_trials", "max_turns",
                "stop_on_harm", "control_fraction", "harm_threshold", "seed",
                "qaly", "orchestration", "judges")


def _canon(obj):
    """Canonical JSON (sorted keys) for hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def manifest(run: dict) -> dict:
    cfg = run.get("config") or {}
    config = {k: cfg.get(k) for k in _CONFIG_KEYS}
    target = run.get("target") or {}  # already secret-free (public_dict)
    seed = cfg.get("seed") or 0
    man = {
        "schema": "sauce.ai/redteam/manifest@1",
        "code_version": CODE_VERSION,
        "target": target,
        "config": config,
        "model_specs": sorted(set((cfg.get("judges") or [])
                                  + ((cfg.get("orchestration") or {}).get("attackers") or [])
                                  + ((cfg.get("orchestration") or {}).get("arbiters") or []))),
        "seed": seed,
        "seed_pinned": bool(seed),
    }
    man["config_hash"] = hashlib.sha256(_canon(
        {"code_version": man["code_version"], "target": target,
         "config": config, "model_specs": man["model_specs"]}).encode()).hexdigest()
    return man


def _persona_fingerprint(personas: list[dict]) -> str:
    return hashlib.sha256(_canon(personas).encode()).hexdigest()


def _recompute_personas(config: dict) -> list[dict]:
    """Regenerate the persona case-mix from a seed-pinned config, mirroring the
    runner's allocation + generation exactly."""
    seed = config.get("seed") or 0
    rng = random.Random(seed)
    allocate_arms(config["n_trials"], config.get("control_fraction", 0.0), rng)
    return [make_persona(rng, config["specialty"], config.get("condition") or None,
                         config.get("focus_harms") or []).as_dict()
            for _ in range(config["n_trials"])]


def verify(store, run_id: str) -> dict:
    """Recompute the case-mix from the manifest and compare to the run's actual
    personas. Reproducible only when the run pinned a (non-zero) seed."""
    run = store.get_run(run_id)
    if not run:
        return {"error": "unknown run"}
    man = manifest(run)
    actual = [t["persona"] for t in store.trials_for_run(run_id, with_turns=False)]
    actual_fp = _persona_fingerprint(actual)
    out = {"config_hash": man["config_hash"], "seed_pinned": man["seed_pinned"],
           "actual_fingerprint": actual_fp}
    if not man["seed_pinned"]:
        out.update(case_mix_reproducible=False,
                   note="seed not pinned (seed=0): personas depended on the run id; pin a seed to reproduce")
        return out
    recomputed = _recompute_personas(man["config"])
    recomputed_fp = _persona_fingerprint(recomputed)
    out.update(recomputed_fingerprint=recomputed_fp,
               case_mix_reproducible=(recomputed_fp == actual_fp))
    if out["case_mix_reproducible"]:
        out["note"] = "the persona case-mix is exactly reproducible from this manifest"
    else:
        out["note"] = "recomputed personas did not match (code or config drift)"
    return out


def capsule(store, run_id: str) -> dict | None:
    run = store.get_run(run_id)
    if not run:
        return None
    man = manifest(run)
    trials = store.trials_for_run(run_id)
    rows = dataset.trial_rows(run, trials)
    adv = ((run.get("summary") or {}).get("adversarial")) or {}
    headline = {
        "status": run.get("status"), "trials": adv.get("trials"),
        "attack_success": (adv.get("conversation_risk") or {}).get("value"),
        "median_prompts_to_harm": (adv.get("prompts_until_harm") or {}).get("km", {}).get("median"),
    }
    return {"manifest": man, "verify": verify(store, run_id),
            "headline": headline, "n_trial_rows": len(rows), "trials": rows}
