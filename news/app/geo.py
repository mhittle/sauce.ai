"""US-only geocoding from a bundled Census 2024 gazetteer subset.

Two lookup entry points:
  - geocode_query(text)  — parse user input from the algo editor; accepts
    ZIP, "City, ST", bare city name, state abbr, or state full name.
  - geocode_place(text)  — looser parse used by the classifier on
    LLM-extracted article locations like "Seattle, WA, USA" or "Texas".

Both return (lat, lng, label) or None. `label` is the canonical
display string the UI / DB stores so users see what we resolved to.

Data lives in news/seed/geo/ as CSV; loaded lazily on first call and
cached for the process lifetime. No network, no dependencies.

haversine_sql() emits a MySQL WHERE-clause fragment computing great-circle
distance in miles against an article_features row's (geo_lat, geo_lng).
MySQL 5.7 has no PostGIS, so the math is inlined; an article whose
geo_lat IS NULL is excluded (radius filtering opts out unresolved rows).
"""
import csv
import os
import re

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "seed", "geo")

_ZIPS = None              # {"98101": (lat, lng)}
_CITIES_BY_KEY = None     # {"seattle": [(state, lat, lng), ...]} — first = largest by area
_CITIES_BY_KEY_STATE = None  # {("seattle", "WA"): (lat, lng)}
_STATES = None            # {"WA": (lat, lng)}
_STATE_NAMES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI",
    "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC", "puerto rico": "PR",
}

_ZIP_RE = re.compile(r"^\s*(\d{5})(?:-\d{4})?\s*$")
_WS_RE = re.compile(r"\s+")


def _data_path(name):
    return os.path.normpath(os.path.join(_DATA_DIR, name))


def _load():
    global _ZIPS, _CITIES_BY_KEY, _CITIES_BY_KEY_STATE, _STATES
    if _ZIPS is not None:
        return
    zips = {}
    with open(_data_path("us_zips.csv"), encoding="utf-8") as f:
        next(f)
        for row in csv.reader(f):
            if len(row) == 3:
                zips[row[0]] = (float(row[1]), float(row[2]))

    by_key = {}
    by_key_state = {}
    with open(_data_path("us_cities.csv"), encoding="utf-8") as f:
        next(f)
        for row in csv.reader(f):
            if len(row) != 4:
                continue
            key, state, lat, lng = row[0], row[1], float(row[2]), float(row[3])
            by_key.setdefault(key, []).append((state, lat, lng))
            by_key_state[(key, state)] = (lat, lng)

    states = {}
    with open(_data_path("us_states.csv"), encoding="utf-8") as f:
        next(f)
        for row in csv.reader(f):
            if len(row) == 3:
                states[row[0]] = (float(row[1]), float(row[2]))

    _ZIPS, _CITIES_BY_KEY, _CITIES_BY_KEY_STATE, _STATES = zips, by_key, by_key_state, states


def _normalize(text):
    """Lowercase, collapse whitespace, strip surrounding punctuation."""
    if not text:
        return ""
    s = text.strip().lower()
    s = _WS_RE.sub(" ", s)
    return s.strip(" .,;:'\"")


def _state_code(token):
    """Resolve a state-ish token to its 2-letter USPS code, or None."""
    t = _normalize(token)
    if not t:
        return None
    if len(t) == 2 and t.upper() in _STATES:
        return t.upper()
    return _STATE_NAMES.get(t)


def geocode_query(text):
    """Resolve user input from the algo editor.

    Order: ZIP, "city, state", bare state, bare city. Returns
    (lat, lng, label) or None. Label is a canonical display string
    (e.g. "Seattle, WA" or "98101") that the editor can echo back so
    the user sees what we resolved.
    """
    if not text:
        return None
    _load()
    raw = text.strip()

    m = _ZIP_RE.match(raw)
    if m:
        zip5 = m.group(1)
        hit = _ZIPS.get(zip5)
        if hit:
            return (hit[0], hit[1], zip5)
        return None

    norm = _normalize(raw)
    if not norm:
        return None

    if "," in norm:
        left, right = [p.strip() for p in norm.split(",", 1)]
        state = _state_code(right)
        if state:
            hit = _CITIES_BY_KEY_STATE.get((left, state))
            if hit:
                return (hit[0], hit[1], f"{left.title()}, {state}")
            # City unknown in that state but state is known — fall through
            # to a state-only match so "Foobar, WA" still narrows by region.
            shit = _STATES.get(state)
            if shit:
                return (shit[0], shit[1], state)

    state = _state_code(norm)
    if state:
        hit = _STATES.get(state)
        if hit:
            return (hit[0], hit[1], state)

    matches = _CITIES_BY_KEY.get(norm)
    if matches:
        state, lat, lng = matches[0]
        return (lat, lng, f"{norm.title()}, {state}")

    return None


def geocode_place(text):
    """Geocode a free-text place mention from the LLM article classifier.

    Strips trailing "USA"/"United States", tries "city, state" then state
    then bare city — same backends as geocode_query but tolerant of
    extra trailing tokens. Returns (lat, lng, label) or None.
    """
    if not text:
        return None
    _load()
    s = _normalize(text)
    for tail in (", usa", ", united states", " usa", " united states"):
        if s.endswith(tail):
            s = s[: -len(tail)].rstrip(", ")
    # Strip a trailing country/region phrase the LLM sometimes adds.
    s = s.rstrip(", ")
    if not s:
        return None
    return geocode_query(s)


# ---------- Haversine SQL (MySQL 5.7-friendly) ----------

_EARTH_MILES = 3958.7613


def haversine_sql(lat, lng, radius_miles, *, lat_col="f.geo_lat", lng_col="f.geo_lng",
                  param_prefix="geo"):
    """Return (sql_fragment, params) computing great-circle distance against
    (lat_col, lng_col) and constraining it to `radius_miles`. Excludes rows
    whose lat column IS NULL (article never resolved to a location).
    """
    p = {
        f"{param_prefix}_lat": float(lat),
        f"{param_prefix}_lng": float(lng),
        f"{param_prefix}_r": float(radius_miles),
        f"{param_prefix}_earth": _EARTH_MILES,
    }
    # Standard haversine: 2 * R * asin(sqrt(sin²(Δφ/2) + cos(φ1) cos(φ2) sin²(Δλ/2)))
    clause = (
        f"({lat_col} IS NOT NULL AND {lng_col} IS NOT NULL AND "
        f"(2 * %({param_prefix}_earth)s * ASIN(SQRT("
        f"POW(SIN(RADIANS({lat_col} - %({param_prefix}_lat)s) / 2), 2) + "
        f"COS(RADIANS(%({param_prefix}_lat)s)) * COS(RADIANS({lat_col})) * "
        f"POW(SIN(RADIANS({lng_col} - %({param_prefix}_lng)s) / 2), 2)"
        f"))) <= %({param_prefix}_r)s)"
    )
    return clause, p
