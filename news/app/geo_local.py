"""Place / radius precedence helpers for the `/local` News Near You page.

The geocoding itself lives in `app.geo`. This module is the pure,
Flask-free piece: given a `?place=` param, a `local_place` cookie, and the
viewer's active weights, decide which of those the page should render
right now. Mirrors the convention of `app/spectrum.py` and
`app/feed_diversify.py` so the precedence logic is unit-testable without a
DB, Flask request context, or the gazetteer CSVs.

Precedence (high to low):
  1. `?place=` -> `geocode_query(place)`; the resolved tuple wins. The
     route also persists it in a `local_place` cookie so subsequent visits
     skip the param.
  2. The `local_place` cookie, if present and parseable.
  3. The viewer's active-profile weights, if they already carry a stored
     `geo_lat` / `geo_lng` / `geo_radius_mi` (a reader who set "Near a
     place" inside `/algo` lands on a working `/local` immediately).
  4. None -> the page renders the empty "set your location" state.

`?radius=` is honored at every layer, clamped to `[1, max]`; a missing /
unparseable / non-positive value falls back to `default_radius`.
"""
from __future__ import annotations

import json
from typing import Callable, Mapping, Optional


COOKIE_NAME = "local_place"
# 1 year, matches the lab_voter_token cookie.
COOKIE_MAX_AGE = 60 * 60 * 24 * 365


def _clamp_radius(raw, *, default_radius: float, max_radius: float) -> float:
    """Coerce `raw` to a positive float in `(0, max_radius]`.

    `None`, empty, garbage, zero, or negative -> `default_radius`. Values
    above `max_radius` are clamped down (so a curious user pasting
    `?radius=99999` still gets a sane query, not a Texas-sized window).
    """
    try:
        r = float(raw)
    except (TypeError, ValueError):
        return float(default_radius)
    if r <= 0:
        return float(default_radius)
    if r > max_radius:
        return float(max_radius)
    return r


def serialize_cookie(place: Mapping) -> str:
    """JSON-encode a resolved place dict for the `local_place` cookie.

    Only writes the four small fields we need to round-trip; ignores extras
    so a future addition doesn't accidentally bloat the cookie.
    """
    return json.dumps({
        "lat": float(place["lat"]),
        "lng": float(place["lng"]),
        "label": str(place.get("label") or ""),
        "radius": float(place["radius"]),
    }, separators=(",", ":"))


def parse_cookie(cookie_value: Optional[str]) -> Optional[dict]:
    """Parse the cookie back into a place dict, or None if malformed.

    Never raises. A missing / empty / non-JSON / wrong-shape / unparseable-
    numeric cookie all return None so the route falls through to the next
    precedence layer (stored weights, then empty state).
    """
    if not cookie_value:
        return None
    try:
        data = json.loads(cookie_value)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        lat = float(data["lat"])
        lng = float(data["lng"])
        radius = float(data["radius"])
    except (KeyError, TypeError, ValueError):
        return None
    label = data.get("label")
    if not isinstance(label, str):
        label = ""
    return {"lat": lat, "lng": lng, "label": label, "radius": radius}


def _place_from_weights(weights: Optional[Mapping], radius: float) -> Optional[dict]:
    """Use the viewer's `/algo` geo filter as the default for `/local`."""
    if not weights:
        return None
    lat = weights.get("geo_lat")
    lng = weights.get("geo_lng")
    if lat is None or lng is None:
        return None
    try:
        lat = float(lat)
        lng = float(lng)
    except (TypeError, ValueError):
        return None
    label = weights.get("geo_label") or weights.get("geo_query") or ""
    if not isinstance(label, str):
        label = ""
    # Prefer the param/cookie-cleaned radius; if the param was absent the
    # caller will have passed `default_radius`. If the algorithm itself
    # has a stored radius we use it as the seed default — but only when
    # the caller hasn't supplied a more specific value via the param.
    stored_radius = weights.get("geo_radius_mi")
    try:
        if stored_radius is not None and float(stored_radius) > 0:
            return {"lat": lat, "lng": lng, "label": label,
                    "radius": float(stored_radius)}
    except (TypeError, ValueError):
        pass
    return {"lat": lat, "lng": lng, "label": label, "radius": radius}


def resolve_local_place(
    place_param: Optional[str],
    radius_param,
    cookie_value: Optional[str],
    weights: Optional[Mapping],
    *,
    default_radius: float,
    max_radius: float,
    geocode: Callable[[str], Optional[tuple]],
) -> tuple[Optional[dict], bool]:
    """Resolve the place to show on `/local`.

    Returns `(place_dict_or_None, should_persist_cookie)`:
      * `place_dict` is `{lat, lng, label, radius}` or None.
      * `should_persist_cookie` is True only when the caller should write a
        fresh cookie (i.e. a new `?place=` resolved successfully). It is
        False for cookie/weights hits and for unresolvable params, so the
        cookie isn't churned on every page view.

    `geocode` is injected (typically `app.geo.geocode_query`) so the helper
    stays pure / unit-testable without the bundled gazetteer CSVs.
    """
    radius = _clamp_radius(radius_param, default_radius=default_radius,
                           max_radius=max_radius)

    # 1) ?place= wins.
    pq = (place_param or "").strip()
    if pq:
        hit = geocode(pq)
        if hit:
            lat, lng, label = hit
            return ({"lat": float(lat), "lng": float(lng),
                     "label": str(label), "radius": radius}, True)
        # Unparseable place: drop through to lower precedence (cookie /
        # weights). UX rationale: the page should still render *something*
        # rather than blanking out a reader who already had a place set.

    # 2) Cookie.
    parsed = parse_cookie(cookie_value)
    if parsed is not None:
        # Honor an explicit ?radius= even when riding the cookie's place,
        # so the radius selector works without a re-geocode.
        if radius_param not in (None, ""):
            parsed = {**parsed, "radius": radius}
        return parsed, False

    # 3) The signed-in viewer's stored algo geo filter.
    from_weights = _place_from_weights(weights, radius)
    if from_weights is not None:
        if radius_param not in (None, ""):
            from_weights = {**from_weights, "radius": radius}
        return from_weights, False

    # 4) Empty state.
    return None, False


def inject_geo_into_weights(weights: Mapping, place: Mapping) -> dict:
    """Return a copy of `weights` with the four geo keys forced to `place`.

    Used by the `/local` route so `ranking.build_filters_sql(weights)` —
    via `_geo_filter_from_weights` — emits the haversine clause for the
    page-chosen place instead of (or in place of) the algo's own setting.
    Pure: does not mutate the input.
    """
    out = dict(weights or {})
    out["geo_lat"] = float(place["lat"])
    out["geo_lng"] = float(place["lng"])
    out["geo_radius_mi"] = float(place["radius"])
    if place.get("label"):
        out["geo_label"] = str(place["label"])
    return out
