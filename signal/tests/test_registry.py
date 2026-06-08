from app.signals.registry import BY_ID, SIGNALS, by_tier, facets


def test_ids_unique():
    ids = [s.id for s in SIGNALS]
    assert len(ids) == len(set(ids))


def test_tiers_valid():
    assert {s.tier for s in SIGNALS} == {"ingested", "derived", "enrichment"}


def test_datatypes_valid():
    assert {s.datatype for s in SIGNALS} <= {"bool", "number", "category",
                                             "text", "geo"}


def test_distress_signals_present():
    for sid in ("distress_stalled", "distress_expiring", "distress_stopwork",
                "distress_renewal", "distress_inspections", "distress_velocity"):
        assert sid in BY_ID


def test_facets_excludes_non_facet_signals():
    facet_ids = {s.id for s in facets()}
    assert "lead_score" not in facet_ids
    assert "cabinet_relevance" in facet_ids


def test_by_tier_counts():
    assert len(by_tier("derived")) > 5
    assert len(by_tier("enrichment")) >= 1
