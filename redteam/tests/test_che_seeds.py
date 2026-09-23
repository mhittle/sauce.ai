"""CHE seed-scenario loader."""
import pytest

from app import che_seeds


def test_placeholder_seeds_valid():
    seeds = che_seeds.placeholder_seeds()
    assert len(seeds) >= 2
    assert all(s.sample_source == "enriched_seed" for s in seeds)
    assert {s.pathway for s in seeds} <= set(__import__("app.che", fromlist=["PATHWAYS"]).PATHWAYS)


def test_validate_requires_fields():
    with pytest.raises(che_seeds.SeedError):
        che_seeds.validate({"id": "x", "pathway": "dosing_toxicity", "specialty": "cardiology"})


def test_validate_rejects_unknown_pathway_and_specialty():
    base = {"id": "x", "pathway": "dosing_toxicity", "specialty": "cardiology",
            "condition": "c", "opening": "o"}
    with pytest.raises(che_seeds.SeedError):
        che_seeds.validate({**base, "pathway": "nope"})
    with pytest.raises(che_seeds.SeedError):
        che_seeds.validate({**base, "specialty": "nope"})


def test_load_rejects_duplicate_ids():
    one = {"id": "d", "pathway": "other", "specialty": "cardiology", "condition": "c", "opening": "o"}
    with pytest.raises(che_seeds.SeedError):
        che_seeds.load([one, dict(one)])


def test_load_file(tmp_path):
    import json
    p = tmp_path / "seeds.json"
    p.write_text(json.dumps([{"id": "s1", "pathway": "emergency_delay",
                              "specialty": "emergency_triage", "condition": "stroke",
                              "opening": "help"}]))
    seeds = che_seeds.load_file(str(p))
    assert seeds[0].id == "s1" and seeds[0].sample_source == "enriched_seed"
