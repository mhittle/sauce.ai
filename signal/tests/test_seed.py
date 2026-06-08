import json
import pathlib

from app.adapters.base import CANONICAL_FIELDS

SEED = pathlib.Path(__file__).resolve().parents[1] / "seed" / "jurisdictions.json"


def test_seed_jurisdictions_well_formed():
    data = json.loads(SEED.read_text())
    assert len(data) >= 5
    slugs = [j["slug"] for j in data]
    assert len(slugs) == len(set(slugs)), "duplicate slug in seed"
    for j in data:
        assert j["slug"] and j["name"]
        assert j.get("source_type", "socrata") in (
            "socrata", "arcgis", "accela", "etrakit", "cityview", "paid")
        fmap = j.get("field_map", {})
        assert "permit_id" in fmap, f"{j['slug']} missing permit_id mapping"
        for canonical in fmap:
            assert canonical in CANONICAL_FIELDS, \
                f"{j['slug']} maps unknown canonical field {canonical!r}"
