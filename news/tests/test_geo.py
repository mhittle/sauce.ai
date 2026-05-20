from app.geo import geocode_query, geocode_place, haversine_sql


def test_zip5_resolves():
    r = geocode_query("98101")
    assert r is not None
    lat, lng, label = r
    assert label == "98101"
    # Downtown Seattle.
    assert 47.4 < lat < 47.8
    assert -122.5 < lng < -122.2


def test_zip_plus_four_strips_suffix():
    r = geocode_query("98101-1234")
    assert r is not None
    assert r[2] == "98101"


def test_city_state_pair():
    r = geocode_query("Seattle, WA")
    assert r is not None
    assert r[2] == "Seattle, WA"
    assert 47.4 < r[0] < 47.8


def test_bare_city_picks_largest_match():
    """Cross-state city names without a state qualifier should resolve to
    the largest matching city by land area (rough population proxy)."""
    r = geocode_query("Phoenix")
    assert r is not None
    # Phoenix, AZ is by far the largest of the four "Phoenix" rows.
    assert r[2] == "Phoenix, AZ"


def test_state_abbr_resolves_to_state_centroid():
    r = geocode_query("TX")
    assert r is not None
    assert r[2] == "TX"
    # Texas is roughly centered around 31°N, -99°W.
    assert 27 < r[0] < 36
    assert -107 < r[1] < -94


def test_state_full_name_resolves():
    r = geocode_query("California")
    assert r is not None
    assert r[2] == "CA"


def test_unknown_query_returns_none():
    assert geocode_query("zzzznotacity") is None
    assert geocode_query("") is None
    assert geocode_query(None) is None


def test_unknown_city_in_known_state_falls_back_to_state():
    """A typo'd city with a real state suffix shouldn't kill the filter —
    fall back to the state centroid so the user still gets *something*."""
    r = geocode_query("zzznotacity, WA")
    assert r is not None
    assert r[2] == "WA"


def test_place_strips_country_suffix():
    """The LLM tends to append ', USA' / ', United States'."""
    a = geocode_query("Seattle, WA")
    b = geocode_place("Seattle, WA, USA")
    assert a == b
    c = geocode_place("Houston, Texas, United States")
    assert c is not None
    assert c[2] == "Houston, TX"


def test_haversine_sql_shape():
    clause, params = haversine_sql(47.6, -122.3, 50)
    assert "f.geo_lat IS NOT NULL" in clause
    assert "ASIN(SQRT(" in clause
    assert "COS(RADIANS(" in clause
    assert params["geo_lat"] == 47.6
    assert params["geo_lng"] == -122.3
    assert params["geo_r"] == 50.0
    # Custom column override flows through.
    clause2, _ = haversine_sql(0, 0, 1, lat_col="x.lat", lng_col="x.lng",
                                param_prefix="g2")
    assert "x.lat" in clause2
    assert "x.lng" in clause2
    assert "%(g2_lat)s" in clause2
