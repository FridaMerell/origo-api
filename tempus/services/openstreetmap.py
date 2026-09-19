"""Building footprints from OpenStreetMap via the Overpass API.

Replaces Lantmäteriet's Byggnad Direkt for the Locale layers: that product is
the full building register and needs a legal review before access is granted
(HTTP 403 without it), while this only needs footprints to draw.

Checked live against overpass-api.de (2026-09-18), rural padded area of about
11 x 11 km:
- ``way["building"](south,west,north,east); out geom;`` returned 11 266
  closed ways in 1.9 s (7 MB raw); every way's ring was closed.
- Each element has ``id``, ``tags`` and ``geometry`` (``[{"lat", "lon"}, ...]``).
- 19 further buildings in the same area are *relations* (multipolygons, e.g.
  with courtyards) - 0.2 %. They are NOT assembled here and are left out.
- The public instance returned HTTP 429 after four queries within ~15 s from
  one IP, so 429/504 are retried with a growing wait (see ``RETRIES``).
Not verified: how long the 429 lasts (the default wait is a guess), and
behaviour on other public Overpass instances.

The data is OpenStreetMap's, under the ODbL: anything showing it must credit
"© OpenStreetMap contributors".
"""

from hashlib import sha256
import json
import time
from typing import Any

from django.conf import settings

from tempus.services.lantmateriet import (
    LantmaterietAPIError,
    LantmaterietConfigurationError,
    LantmaterietMapTooLargeError,
    LantmaterietRateLimitedError,
    _cache_singleflight,
)


class OverpassConfigurationError(LantmaterietConfigurationError):
    """Raised when the Overpass integration has no endpoint configured."""


class OverpassAPIError(LantmaterietAPIError):
    """Raised when Overpass cannot serve a complete, valid response."""


class OverpassMapTooLargeError(LantmaterietMapTooLargeError):
    """Raised when an area holds more buildings than the safety limit."""


def _config() -> dict[str, Any]:
    return getattr(settings, "OVERPASS_API", {}) or {}


def _polygonal_parts(geometry: Any) -> list[Any]:
    """The Polygon parts of a clip result (a clip can also yield lines/points)."""
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    return [
        part
        for member in getattr(geometry, "geoms", [])
        for part in _polygonal_parts(member)
    ]


def _prepare(geometry: dict[str, Any]) -> tuple[Any, dict[str, Any], str]:
    """Parse ``geometry`` and return ``(shapely shape, config, "south,west,north,east")``."""
    try:
        from shapely.geometry import shape
    except ImportError as exc:
        raise OverpassConfigurationError("Shapely is required for OpenStreetMap layers.") from exc

    try:
        target = shape(geometry)
    except (TypeError, ValueError, KeyError) as exc:
        raise OverpassAPIError("Geometry is not valid GeoJSON.") from exc

    config = _config()
    if not config.get("URL"):
        raise OverpassConfigurationError("Configure OVERPASS_URL.")
    if target.is_empty:
        return target, config, ""

    west, south, east, north = target.bounds
    return target, config, f"{south:.6f},{west:.6f},{north:.6f},{east:.6f}"


def _cache_key(prefix: str, geometry: dict[str, Any]) -> str:
    return f"{prefix}:" + sha256(
        json.dumps(geometry, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _overpass_elements(query_body: str, config: dict[str, Any]) -> list[dict[str, Any]]:
    """Run an Overpass query (without its ``[out:json]`` header) and return its elements.

    Fails rather than returning a partial result: HTTP errors, unreadable JSON
    and Overpass's own "stopped early" remarks all raise.
    """
    import requests

    timeout = int(config.get("TIMEOUT", 120))
    query = f"[out:json][timeout:{timeout}];{query_body}"

    # The public instance limits per-IP query slots: several quick queries
    # in a row got a real HTTP 429 in testing. 429 (busy) and 504 (timeout
    # while busy) are transient, so wait and retry before failing, since a
    # failure here fails the whole all-or-nothing Locale prefetch.
    attempts = int(config.get("RETRIES", 3))
    for attempt in range(attempts):
        try:
            response = requests.post(
                config["URL"],
                data={"data": query},
                headers={"User-Agent": config.get("USER_AGENT", "origo-tempus")},
                timeout=timeout + 15,
            )
        except requests.RequestException as exc:
            raise OverpassAPIError("Could not reach Overpass.") from exc
        if response.status_code not in (429, 504) or attempt == attempts - 1:
            break
        time.sleep(config.get("RETRY_WAIT_SECONDS", 10) * (attempt + 1))

    if response.status_code == 429:
        raise LantmaterietRateLimitedError("Overpass is rate limiting requests.")
    if not response.ok:
        raise OverpassAPIError(f"Overpass returned HTTP {response.status_code}.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise OverpassAPIError("Overpass returned invalid JSON.") from exc

    # Overpass answers 200 with a "remark" (and possibly partial data) when
    # it ran out of time or memory; that must fail, not be stored as complete.
    remark = payload.get("remark")
    if remark and ("runtime error" in remark or "timed out" in remark):
        raise OverpassAPIError(f"Overpass stopped early: {remark}")
    return payload.get("elements") or []


# Named places worth showing on a map. Excludes city_block/block/square (urban
# blocks and squares: 104 of 236 named `place` objects in a sampled rural area)
# and municipality (an administrative unit, not a place to point at).
PLACE_TYPES = (
    "city", "town", "village", "hamlet", "isolated_dwelling", "farm",
    "locality", "suburb", "neighbourhood", "quarter", "island", "islet",
)


def place_names_in_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
    """Return named OpenStreetMap places (villages, hamlets, farms, ...) inside a geometry.

    One Overpass query for the geometry's bbox, then a Shapely point-in-shape
    filter, so unlike ``lantmateriet.place_name_nearest`` this covers the
    whole area completely in a single request. Each feature is a Point (a
    way's or relation's ``center``); OSM tags are passed through unchanged
    under ``properties`` (``name``, ``place``, ...). Raises
    ``OverpassMapTooLargeError`` above ``MAX_FEATURES``.
    """
    from shapely.geometry import Point, mapping
    from shapely.prepared import prep

    target, config, bbox = _prepare(geometry)
    if target.is_empty:
        return {"type": "FeatureCollection", "features": []}

    place_filter = "|".join(PLACE_TYPES)
    query_body = f'nwr["name"]["place"~"^({place_filter})$"]({bbox});out center tags qt;'

    def _fetch() -> dict[str, Any]:
        elements = _overpass_elements(query_body, config)
        if len(elements) > config.get("MAX_FEATURES", 30000):
            raise OverpassMapTooLargeError(
                "The requested area contains too many named places; choose a smaller area."
            )
        covered = prep(target)
        features = []
        for element in elements:
            position = element if "lat" in element else element.get("center") or {}
            if "lat" not in position or "lon" not in position:
                continue
            point = Point(position["lon"], position["lat"])
            if not covered.covers(point):
                continue
            features.append(
                {
                    "collection": "openstreetmap",
                    "feature_id": f"{element.get('type')}/{element.get('id')}",
                    "kind": "place_name",
                    "properties": element.get("tags") or {},
                    "geometry": mapping(point),
                }
            )
        return {"type": "FeatureCollection", "features": features}

    return _cache_singleflight(
        _cache_key("overpass-place-names", geometry),
        config.get("CACHE_SECONDS", 60 * 60 * 24 * 30),
        _fetch,
    )


def buildings_in_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
    """Return OpenStreetMap building footprints clipped to a GeoJSON geometry.

    Overpass filters by bbox only, so the geometry's bounding box is queried
    and each footprint is then clipped to the exact geometry with Shapely,
    like ``lantmateriet.land_cover_map``. OSM tags are passed through
    unchanged under ``properties``. Raises ``OverpassMapTooLargeError`` when
    more than ``MAX_FEATURES`` buildings fall inside the bbox, and
    ``OverpassAPIError`` when Overpass reports it stopped early (a partial
    result is never returned).
    """
    from shapely import make_valid
    from shapely.geometry import MultiPolygon, Polygon, mapping
    from shapely.prepared import prep

    target, config, bbox = _prepare(geometry)
    if target.is_empty:
        return {"type": "FeatureCollection", "features": []}

    query_body = f'way["building"]["building"!="no"]({bbox});out geom qt;'

    def _fetch() -> dict[str, Any]:
        elements = _overpass_elements(query_body, config)
        if len(elements) > config.get("MAX_FEATURES", 30000):
            raise OverpassMapTooLargeError(
                "The requested area contains too many buildings; choose a smaller area."
            )

        covered = prep(target)
        features = []
        for element in elements:
            ring = [
                (point["lon"], point["lat"])
                for point in element.get("geometry") or []
                if "lon" in point and "lat" in point
            ]
            if element.get("type") != "way" or len(ring) < 4:
                continue
            footprint = Polygon(ring)
            if not footprint.is_valid:
                footprint = make_valid(footprint)
            clipped = footprint if covered.contains(footprint) else footprint.intersection(target)
            parts = _polygonal_parts(clipped)
            if not parts:
                continue
            clipped = parts[0] if len(parts) == 1 else MultiPolygon(parts)
            features.append(
                {
                    "collection": "openstreetmap",
                    "feature_id": f"way/{element.get('id')}",
                    "kind": "building",
                    "properties": element.get("tags") or {},
                    "geometry": mapping(clipped),
                }
            )
        return {"type": "FeatureCollection", "features": features}

    return _cache_singleflight(
        _cache_key("overpass-buildings", geometry),
        config.get("CACHE_SECONDS", 60 * 60 * 24 * 30),
        _fetch,
    )
