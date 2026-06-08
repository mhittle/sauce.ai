from app.ingest.dedup import (dedup_confidence, dedup_key, group_permits,
                              normalize_address, normalize_apn)


def test_normalize_address_canonicalizes():
    a = normalize_address("123 North Main Street")
    b = normalize_address("123 N Main St")
    assert a == b == "123 n main st"
    # directional + suffix + suite abbreviations are folded
    assert normalize_address("500 West Peachtree Avenue, Suite 10") \
        == "500 w peachtree ave ste 10"


def test_normalize_apn_strips_punctuation():
    assert normalize_apn("123-45-678") == normalize_apn("1234 5678") \
        == "12345678"


def test_dedup_key_prefers_apn_then_address_then_permit():
    assert dedup_key({"parcel_apn": "123-45", "address": "1 Main St",
                      "permit_id": "P1"}) == ("apn", "12345")
    assert dedup_key({"address": "1 Main St", "permit_id": "P1"}) \
        == ("address", "1 main st")
    assert dedup_key({"permit_id": "P1"}) == ("permit", "P1")


def test_dedup_confidence_ranking():
    assert dedup_confidence("apn") > dedup_confidence("address") \
        > dedup_confidence("permit")


def test_group_permits_collapses_same_parcel():
    permits = [
        {"parcel_apn": "999", "permit_id": "A"},
        {"parcel_apn": "999", "permit_id": "B"},
        {"parcel_apn": "111", "permit_id": "C"},
    ]
    groups = group_permits(permits)
    assert len(groups) == 2
    assert len(groups[("apn", "999")]) == 2
