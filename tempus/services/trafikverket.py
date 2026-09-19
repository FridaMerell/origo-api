"""Client for Trafikverket's open API (NVDB road data, object type "Vägnummer").

Unlike the Lantmäteriet products this is one XML-over-POST endpoint: the API
key travels inside the request body, not in an ``Authorization`` header, so
``lantmateriet._authorization_header`` does not apply here.

Confirmed live against the real API (2026-09-18) with a small bbox:
- ``WITHIN shape="box"`` takes ``"lon lat, lon lat"`` (comma-separated
  corners). The space-only form ``"lon lat lon lat"`` is rejected with HTTP 400.
- The geometry field name must carry its dimension suffix, exactly
  ``Geometry.WKT-WGS84-3D`` - the suffix is undocumented but required, in both
  the filter and ``EXCLUDE``.
- ``limit`` up to at least 5000 and ``skip`` paging are accepted.
- Every field of a row is returned when no ``INCLUDE`` is given; ``EXCLUDE``
  of the SWEREF 99 TM geometry keeps all the others.
- Rows in the sampled area were all current (``Deleted`` false,
  ``Valid_To`` 9999-12-31); the validity filter below is still applied since
  the source versions its data.
Not verified: behaviour at the exact page-size limit and error bodies for a
rate-limited key.
"""

from datetime import date
from hashlib import sha256
import json
from typing import Any
from xml.sax.saxutils import quoteattr

from django.conf import settings

from tempus.services.lantmateriet import (
    LantmaterietAPIError,
    LantmaterietConfigurationError,
    LantmaterietMapTooLargeError,
    LantmaterietRateLimitedError,
    _cache_singleflight,
)

OBJECT_TYPE = "Vägnummer"
NAMESPACE = "Vägdata.NVDB_DK_O"
SCHEMA_VERSION = "1.2"
GEOMETRY_FIELD = "Geometry.WKT-WGS84-3D"
EXCLUDED_GEOMETRY_FIELD = "Geometry.WKT-SWEREF99TM-3D"


class TrafikverketConfigurationError(LantmaterietConfigurationError):
    """Raised when the Trafikverket integration lacks its API key or URL."""


class TrafikverketAPIError(LantmaterietAPIError):
    """Raised when Trafikverket cannot serve a valid response."""


class TrafikverketMapTooLargeError(LantmaterietMapTooLargeError):
    """Raised when an area would return more road segments than the safety limit."""


def _config() -> dict[str, Any]:
    return getattr(settings, "TRAFIKVERKET_API", {}) or {}


def _query_xml(token: str, bbox: tuple[float, float, float, float], limit: int, skip: int) -> str:
    min_lon, min_lat, max_lon, max_lat = bbox
    corners = f"{min_lon:.7f} {min_lat:.7f}, {max_lon:.7f} {max_lat:.7f}"
    return (
        "<REQUEST>"
        f"<LOGIN authenticationkey={quoteattr(token)} />"
        f'<QUERY objecttype="{OBJECT_TYPE}" namespace="{NAMESPACE}" '
        f'schemaversion="{SCHEMA_VERSION}" limit="{limit}" skip="{skip}">'
        f'<FILTER><WITHIN name="{GEOMETRY_FIELD}" shape="box" value="{corners}" /></FILTER>'
        f"<EXCLUDE>{EXCLUDED_GEOMETRY_FIELD}</EXCLUDE>"
        "</QUERY>"
        "</REQUEST>"
    )


def _post(config: dict[str, Any], xml: str) -> list[dict[str, Any]]:
    import requests

    try:
        response = requests.post(
            config["URL"],
            data=xml.encode("utf-8"),
            headers={"Content-Type": "text/xml"},
            timeout=config.get("TIMEOUT", 30),
        )
    except requests.RequestException as exc:
        raise TrafikverketAPIError("Could not reach Trafikverket.") from exc

    if response.status_code == 429:
        raise LantmaterietRateLimitedError("Trafikverket is rate limiting requests.")

    try:
        result = response.json()["RESPONSE"]["RESULT"][0]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise TrafikverketAPIError(
            f"Trafikverket returned an unreadable response (HTTP {response.status_code})."
        ) from exc

    error = result.get("ERROR")
    if error:
        message = error.get("MESSAGE") if isinstance(error, dict) else str(error)
        raise TrafikverketAPIError(f"Trafikverket rejected the query: {message}")
    if not response.ok:
        raise TrafikverketAPIError(f"Trafikverket returned HTTP {response.status_code}.")
    return result.get(OBJECT_TYPE) or []


def _is_current(row: dict[str, Any], today: str) -> bool:
    """Currently valid, not soft-deleted. ISO dates compare correctly as strings."""
    if row.get("Deleted"):
        return False
    valid_from = row.get("Valid_From") or ""
    valid_to = row.get("Valid_To") or "9999-12-31"
    return valid_from <= today < valid_to


def roads_in_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
    """Return current road segments clipped to a GeoJSON geometry, as a FeatureCollection.

    Trafikverket filters by bbox only, so the geometry's bounding box is
    queried (paged with ``skip``) and each segment is then clipped to the exact
    geometry with Shapely, like ``lantmateriet.land_cover_map``. Coordinates
    come back as WGS 84 WKT; elevation is dropped (``force_2d``) since the map
    layer has no use for it and it is a third of the coordinate payload.
    Upstream attributes are passed through unchanged under ``properties``
    (linear-referencing fields such as ``Start_Measure``/``Seq_No`` included).

    Raises ``TrafikverketMapTooLargeError`` when more than ``MAX_FEATURES``
    segments fall inside the bbox rather than returning a partial layer.
    """
    try:
        from shapely import force_2d, wkt
        from shapely.errors import ShapelyError
        from shapely.geometry import mapping, shape
    except ImportError as exc:
        raise TrafikverketConfigurationError("Shapely is required for road geometry.") from exc

    try:
        target = shape(geometry)
    except (TypeError, ValueError, KeyError) as exc:
        raise TrafikverketAPIError("Geometry is not valid GeoJSON.") from exc
    if target.is_empty:
        return {"type": "FeatureCollection", "features": []}

    config = _config()
    token = config.get("TOKEN")
    if not token or not config.get("URL"):
        raise TrafikverketConfigurationError(
            "Configure TRAFIKVERKET_TOKEN (and optionally TRAFIKVERKET_URL)."
        )

    bbox = target.bounds
    page_size = config.get("PAGE_SIZE", 1000)
    max_features = config.get("MAX_FEATURES", 20000)
    cache_key = "trafikverket-roads:" + sha256(
        json.dumps(geometry, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    def _fetch() -> dict[str, Any]:
        today = date.today().isoformat()
        features: dict[Any, dict[str, Any]] = {}
        seen = 0
        skip = 0
        while True:
            rows = _post(config, _query_xml(token, bbox, page_size, skip))
            seen += len(rows)
            if seen > max_features:
                raise TrafikverketMapTooLargeError(
                    "The requested area contains too many road segments; choose a smaller area."
                )
            for row in rows:
                if not _is_current(row, today):
                    continue
                wkt_string = (row.get("Geometry") or {}).get("WKT-WGS84-3D")
                if not wkt_string:
                    continue
                try:
                    clipped = force_2d(wkt.loads(wkt_string).intersection(target))
                except ShapelyError as exc:
                    raise TrafikverketAPIError(
                        "Trafikverket returned an invalid road geometry."
                    ) from exc
                if clipped.is_empty:
                    continue
                gid = row.get("GID")
                features.setdefault(
                    gid,
                    {
                        "collection": OBJECT_TYPE,
                        "feature_id": gid,
                        "kind": "road",
                        "properties": {k: v for k, v in row.items() if k != "Geometry"},
                        "geometry": mapping(clipped),
                    },
                )
            if len(rows) < page_size:
                break
            skip += page_size
        return {"type": "FeatureCollection", "features": list(features.values())}

    return _cache_singleflight(cache_key, config.get("CACHE_SECONDS", 60 * 60 * 24 * 30), _fetch)
