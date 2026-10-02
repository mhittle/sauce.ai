"""Reproducibility capsule: manifest, config hash, determinism check, capsule."""
import random

from fastapi.testclient import TestClient

from app import repro
from app.config import Settings
from app.main import create_app
from app.personas import make_persona
from app.runner import Runner, RunSpec, allocate_arms
from app.store import Store
from app.targets import TargetConfig


def _seed_run(store, *, seed, n=8, model="bot-x"):
    """Create a completed run whose stored personas are generated exactly as the
    runner does for the given seed/config."""
    settings = Settings(db_path=":memory:")
    spec = RunSpec(email="me@lab.edu", n_trials=n, specialty="endocrinology",
                   focus_harms=["dosing_error"], seed=seed, control_fraction=0.0,
                   orchestration={"attackers": ["mock:a"]}, judges=["mock:j"])
    target = TargetConfig(kind="openai_chat", url="https://api.x/v1/chat", model=model,
                          api_key="SECRET-should-not-persist")
    run_id = store.create_run(spec.email, n, spec.public_dict(settings), target.public_dict(), 0.0)
    # mirror runner persona generation
    rng = random.Random(seed or run_id)
    allocate_arms(n, 0.0, rng)
    for idx in range(n):
        persona = make_persona(rng, "endocrinology", None, ["dosing_error"])
        tid = store.create_trial(run_id, idx, "adversarial", persona.as_dict())
        store.finish_trial(tid, status="complete", n_turns=1, first_harm_turn=None)
    store.update_run(run_id, status="complete", summary={"adversarial": {"trials": n,
                     "conversation_risk": {"value": 0.0}, "prompts_until_harm": {"km": {"median": None}}}})
    return run_id


# -- manifest -----------------------------------------------------------------

def test_manifest_has_hash_and_no_secrets():
    store = Store(":memory:")
    rid = _seed_run(store, seed=42)
    man = repro.manifest(store.get_run(rid))
    assert len(man["config_hash"]) == 64
    assert man["seed_pinned"] is True
    assert "api_key" not in man["target"]
    assert "SECRET" not in repro._canon(man)
    assert "mock:a" in man["model_specs"] and "mock:j" in man["model_specs"]
    assert man["model_specs"] == sorted(man["model_specs"])  # canonical order


def test_config_hash_stable_and_sensitive():
    store = Store(":memory:")
    r1 = _seed_run(store, seed=42)
    r2 = _seed_run(store, seed=42, model="bot-x")  # same config incl. model+seed
    r3 = _seed_run(store, seed=99)                 # different seed
    h1 = repro.manifest(store.get_run(r1))["config_hash"]
    h2 = repro.manifest(store.get_run(r2))["config_hash"]
    h3 = repro.manifest(store.get_run(r3))["config_hash"]
    assert h1 == h2       # identical config -> identical hash
    assert h1 != h3       # seed is part of the config


# -- determinism check --------------------------------------------------------

def test_verify_reproducible_for_pinned_seed():
    store = Store(":memory:")
    rid = _seed_run(store, seed=42)
    v = repro.verify(store, rid)
    assert v["seed_pinned"] is True
    assert v["case_mix_reproducible"] is True
    assert v["recomputed_fingerprint"] == v["actual_fingerprint"]


def test_verify_not_reproducible_without_seed():
    store = Store(":memory:")
    rid = _seed_run(store, seed=0)
    v = repro.verify(store, rid)
    assert v["seed_pinned"] is False
    assert v["case_mix_reproducible"] is False
    assert "pin a seed" in v["note"]


def test_capsule_bundles_everything():
    store = Store(":memory:")
    rid = _seed_run(store, seed=42)
    cap = repro.capsule(store, rid)
    assert cap["manifest"]["config_hash"]
    assert cap["verify"]["case_mix_reproducible"] is True
    assert cap["n_trial_rows"] == 8 and len(cap["trials"]) == 8
    assert cap["headline"]["trials"] == 8


# -- API ----------------------------------------------------------------------

def test_repro_endpoints():
    store = Store(":memory:")
    settings = Settings(db_path=":memory:")
    app = create_app(settings, store, Runner(settings, store, mocks={}))
    rid = _seed_run(store, seed=42)
    c = TestClient(app)
    man = c.get(f"/runs/{rid}/manifest.json").json()
    assert man["config_hash"] and "api_key" not in man["target"]
    v = c.get(f"/runs/{rid}/verify.json").json()
    assert v["case_mix_reproducible"] is True
    cap = c.get(f"/runs/{rid}/capsule.json").json()
    assert cap["manifest"]["config_hash"] == man["config_hash"]
    assert c.get("/runs/ghost/manifest.json").status_code == 404
