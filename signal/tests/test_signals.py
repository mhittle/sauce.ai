from datetime import date, timedelta

from app.signals import derived as d
from app.signals.derived import ProjectContext, compute_project_signals

TODAY = date(2026, 6, 8)


def test_value_tier_buckets():
    assert d.value_tier(6_000_000) == "mega"
    assert d.value_tier(2_000_000) == "large"
    assert d.value_tier(300_000) == "mid"
    assert d.value_tier(60_000) == "small"
    assert d.value_tier(1_000) == "micro"
    assert d.value_tier(None) is None


def test_cabinet_relevance_and_intensity():
    rel = d.cabinet_relevance("new cabinet millwork and kitchen casework")
    assert rel == 1.0
    assert d.casework_intensity(rel) == "high"
    assert d.casework_intensity(0.0) == "none"


def test_classify_category_restaurant():
    assert d.classify_category("restaurant kitchen build-out dining") == "restaurant"
    assert d.classify_category("new hotel resort tower") == "hospitality"


def test_is_commercial():
    assert d.is_commercial("tenant improvement for office", None) is True
    assert d.is_commercial("single family dwelling remodel", None) is False


def test_distress_stalled():
    old = TODAY - timedelta(days=400)
    ctx = ProjectContext(permits=[{"issue_date": old, "status": "issued"}],
                         today=TODAY)
    assert d.distress_stalled(ctx) is True
    # recent status change clears it
    ctx2 = ProjectContext(
        permits=[{"issue_date": old, "status": "issued",
                  "last_status_change": TODAY - timedelta(days=10)}], today=TODAY)
    assert d.distress_stalled(ctx2) is False
    # finaled never stalled
    ctx3 = ProjectContext(permits=[{"issue_date": old, "status": "finaled"}],
                          today=TODAY)
    assert d.distress_stalled(ctx3) is False


def test_distress_expiring_and_stopwork_and_renewal_and_inspections():
    soon = TODAY + timedelta(days=10)
    assert d.distress_expiring(
        ProjectContext(permits=[{"expiration_date": soon}], today=TODAY)) is True
    assert d.distress_stopwork([{"status": "STOP WORK"}]) is True
    assert d.distress_renewal([{"permit_subtype": "Renewal/Extension"}]) is True
    assert d.distress_inspections(
        [{"result": "fail"}, {"result": "reinspect"}]) is True
    assert d.distress_inspections([{"result": "pass"}]) is False


def test_geo_shippable_distance():
    # facility and a nearby point ~ within radius
    ctx = ProjectContext(
        permits=[{"latitude": 33.75, "longitude": -84.39}],
        facility=(33.74, -84.38), shippable_radius_mi=500, today=TODAY)
    out = compute_project_signals(ctx)
    assert out["geo_shippable"] is True
    assert out["distance_mi"] < 5


def test_compute_project_signals_end_to_end():
    old = TODAY - timedelta(days=400)
    ctx = ProjectContext(
        permits=[{
            "work_description": "tenant improvement restaurant kitchen casework",
            "use_type": "commercial", "valuation": 750_000,
            "status": "issued", "issue_date": old,
            "contractor_name": "Acme Builders LLC",
            "latitude": 33.75, "longitude": -84.39,
        }],
        today=TODAY, facility=(33.74, -84.38),
        known_contractors=frozenset({"acme builders"}))
    out = compute_project_signals(ctx)
    assert out["is_commercial"] is True
    assert out["category"] == "restaurant"
    assert out["value_tier"] == "mid"
    assert out["cabinet_relevance"] > 0
    assert out["distress_stalled"] is True
    assert out["known_gc"] is True
    assert out["new_gc"] is False
