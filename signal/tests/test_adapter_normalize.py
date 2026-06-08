from datetime import date

from app.adapters.base import (NormalizedPermit, normalize_record, parse_date,
                               parse_number)


def test_parse_date_formats():
    assert parse_date("2026-01-15T00:00:00.000") == date(2026, 1, 15)
    assert parse_date("01/15/2026") == date(2026, 1, 15)
    assert parse_date("2026-01-15") == date(2026, 1, 15)
    assert parse_date("") is None
    assert parse_date(None) is None


def test_parse_number_strips_currency():
    assert parse_number("$1,250,000.50") == 1250000.50
    assert parse_number("") is None
    assert parse_number("n/a") is None
    assert parse_number(42) == 42.0


def test_normalize_record_maps_and_coerces():
    record = {
        "permit_": "PB-123",
        "reported_cost": "$500,000",
        "issue_date": "2026-02-01T00:00:00",
        "work_description": "  Tenant improvement, restaurant build-out  ",
        "lat": "41.88", "lng": "-87.63",
    }
    field_map = {
        "permit_id": "permit_", "valuation": "reported_cost",
        "issue_date": "issue_date", "work_description": "work_description",
        "latitude": "lat", "longitude": "lng",
    }
    norm = normalize_record(record, field_map)
    assert isinstance(norm, NormalizedPermit)
    assert norm.permit_id == "PB-123"
    assert norm.valuation == 500000.0
    assert norm.issue_date == date(2026, 2, 1)
    assert norm.work_description == "Tenant improvement, restaurant build-out"
    assert norm.latitude == 41.88 and norm.longitude == -87.63
    assert norm.raw_payload == record


def test_normalize_record_drops_without_permit_id():
    assert normalize_record({"foo": "bar"}, {"permit_id": "missing"}) is None


def test_normalize_record_handles_nested_location_key():
    record = {"permit_number": "X1", "location": {"latitude": "37.77",
                                                  "longitude": "-122.41"}}
    fmap = {"permit_id": "permit_number", "latitude": "location.latitude",
            "longitude": "location.longitude"}
    norm = normalize_record(record, fmap)
    assert norm.latitude == 37.77 and norm.longitude == -122.41
