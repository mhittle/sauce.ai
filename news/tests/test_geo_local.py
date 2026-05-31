"""Pure tests for `app.geo_local` precedence + cookie round-trip.

These tests do not import Flask, the DB, or the bundled gazetteer CSVs.
`geocode_query` is injected as a small fake so the precedence behavior is
fully isolated from the actual geo data — see the `app.geo` tests for
geocoding coverage.
"""
import json

from app.geo_local import (
    inject_geo_into_weights, parse_cookie, resolve_local_place,
    serialize_cookie,
)


# A small deterministic geocoder. Matches the `(lat, lng, label)` tuple
# shape of the real `geocode_query` but only knows about a handful of
# places. Returns None for anything else, just like the real one.
_FAKE_DB = {
    "seattle": (47.6, -122.3, "Seattle, WA"),
    "98101": (47.61, -122.33, "98101"),
    "tx": (31.0, -99.0, "TX"),
}


def _geocode(text):
    if not text:
        return None
    return _FAKE_DB.get(text.strip().lower())


def _resolve(**overrides):
    """Test helper: call resolve_local_place with sensible defaults."""
    kwargs = dict(
        place_param=None,
        radius_param=None,
        cookie_value=None,
        weights=None,
        default_radius=50.0,
        max_radius=500.0,
        geocode=_geocode,
    )
    kwargs.update(overrides)
    return resolve_local_place(**kwargs)


# ---------- precedence ----------

def test_place_param_beats_cookie_beats_weights():
    """Param wins outright."""
    cookie = serialize_cookie({"lat": 1.0, "lng": 2.0, "label": "X",
                               "radius": 25.0})
    weights = {"geo_lat": 33.0, "geo_lng": -97.0, "geo_label": "Dallas, TX",
               "geo_radius_mi": 100.0}
    place, persist = _resolve(place_param="Seattle", cookie_value=cookie,
                              weights=weights)
    assert place is not None
    assert place["label"] == "Seattle, WA"
    assert place["lat"] == 47.6
    assert persist is True  # successful param resolve -> persist cookie


def test_cookie_beats_weights_when_no_param():
    cookie = serialize_cookie({"lat": 40.7, "lng": -74.0, "label": "NYC",
                               "radius": 30.0})
    weights = {"geo_lat": 33.0, "geo_lng": -97.0, "geo_label": "Dallas, TX",
               "geo_radius_mi": 100.0}
    place, persist = _resolve(cookie_value=cookie, weights=weights)
    assert place == {"lat": 40.7, "lng": -74.0, "label": "NYC", "radius": 30.0}
    assert persist is False  # cookie hits don't re-persist


def test_weights_used_when_no_param_or_cookie():
    weights = {"geo_lat": 33.0, "geo_lng": -97.0, "geo_label": "Dallas, TX",
               "geo_radius_mi": 100.0}
    place, persist = _resolve(weights=weights)
    assert place is not None
    assert place["lat"] == 33.0
    assert place["label"] == "Dallas, TX"
    assert place["radius"] == 100.0
    assert persist is False


def test_weights_radius_falls_back_to_default_when_missing():
    """A signed-in user whose `/algo` has only lat/lng (radius cleared)
    should get the default radius rather than a zero-radius filter."""
    weights = {"geo_lat": 33.0, "geo_lng": -97.0, "geo_label": "Dallas, TX"}
    place, _ = _resolve(weights=weights, default_radius=75.0)
    assert place is not None
    assert place["radius"] == 75.0


def test_no_signal_returns_empty_state():
    place, persist = _resolve()
    assert place is None
    assert persist is False


# ---------- unresolvable param falls through, not 500 ----------

def test_unresolvable_param_falls_through_to_cookie():
    cookie = serialize_cookie({"lat": 40.7, "lng": -74.0, "label": "NYC",
                               "radius": 30.0})
    place, persist = _resolve(place_param="zzznotacity", cookie_value=cookie)
    assert place is not None
    assert place["label"] == "NYC"
    assert persist is False


def test_unresolvable_param_with_nothing_to_fall_back_on_is_none():
    place, persist = _resolve(place_param="zzznotacity")
    assert place is None
    assert persist is False


# ---------- radius handling ----------

def test_radius_param_clamps_to_max():
    place, _ = _resolve(place_param="Seattle", radius_param="9999",
                        max_radius=500.0)
    assert place is not None
    assert place["radius"] == 500.0


def test_radius_param_negative_or_zero_falls_back_to_default():
    p1, _ = _resolve(place_param="Seattle", radius_param="0",
                     default_radius=50.0)
    p2, _ = _resolve(place_param="Seattle", radius_param="-5",
                     default_radius=50.0)
    assert p1["radius"] == 50.0
    assert p2["radius"] == 50.0


def test_radius_param_garbage_falls_back_to_default():
    place, _ = _resolve(place_param="Seattle", radius_param="abc",
                        default_radius=50.0)
    assert place["radius"] == 50.0


def test_radius_param_overrides_cookie_radius():
    """A user using the radius dropdown over a cookie-stored place should
    see the new radius applied without re-geocoding."""
    cookie = serialize_cookie({"lat": 40.7, "lng": -74.0, "label": "NYC",
                               "radius": 30.0})
    place, _ = _resolve(cookie_value=cookie, radius_param="100")
    assert place["lat"] == 40.7  # same place
    assert place["radius"] == 100.0  # new radius


# ---------- cookie parse / serialize ----------

def test_malformed_cookie_returns_none():
    assert parse_cookie(None) is None
    assert parse_cookie("") is None
    assert parse_cookie("not-json") is None
    assert parse_cookie("[1, 2, 3]") is None  # wrong shape (not dict)
    assert parse_cookie('{"lat": "abc", "lng": 1, "radius": 1}') is None
    assert parse_cookie('{"lat": 1}') is None  # missing fields


def test_cookie_roundtrip():
    place = {"lat": 47.6, "lng": -122.3, "label": "Seattle, WA",
             "radius": 50.0}
    parsed = parse_cookie(serialize_cookie(place))
    assert parsed == place


def test_cookie_with_label_none_becomes_empty_string():
    cookie = json.dumps({"lat": 1.0, "lng": 2.0, "label": None,
                         "radius": 10.0})
    parsed = parse_cookie(cookie)
    assert parsed == {"lat": 1.0, "lng": 2.0, "label": "", "radius": 10.0}


def test_malformed_cookie_falls_through_to_weights():
    weights = {"geo_lat": 33.0, "geo_lng": -97.0, "geo_label": "Dallas, TX",
               "geo_radius_mi": 100.0}
    place, _ = _resolve(cookie_value="garbage{{{", weights=weights)
    assert place is not None
    assert place["label"] == "Dallas, TX"


# ---------- weight injection ----------

def test_inject_geo_overrides_weights():
    weights = {"objectivity": 1.0, "geo_lat": 1.0, "geo_lng": 2.0,
               "geo_radius_mi": 10.0, "geo_label": "old"}
    place = {"lat": 47.6, "lng": -122.3, "label": "Seattle, WA",
             "radius": 50.0}
    out = inject_geo_into_weights(weights, place)
    assert out["geo_lat"] == 47.6
    assert out["geo_lng"] == -122.3
    assert out["geo_radius_mi"] == 50.0
    assert out["geo_label"] == "Seattle, WA"
    # Other weights are preserved verbatim.
    assert out["objectivity"] == 1.0
    # Pure: input is not mutated.
    assert weights["geo_lat"] == 1.0
    assert weights["geo_label"] == "old"


def test_inject_geo_works_on_empty_weights():
    out = inject_geo_into_weights({}, {"lat": 1.0, "lng": 2.0,
                                        "label": "X", "radius": 25.0})
    assert out == {"geo_lat": 1.0, "geo_lng": 2.0, "geo_radius_mi": 25.0,
                   "geo_label": "X"}


def test_inject_geo_handles_none_weights():
    out = inject_geo_into_weights(None, {"lat": 1.0, "lng": 2.0,
                                          "label": "", "radius": 25.0})
    assert out == {"geo_lat": 1.0, "geo_lng": 2.0, "geo_radius_mi": 25.0}
