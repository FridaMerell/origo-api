"""Client for Lantmäteriet's Marktäcke Direkt OGC API Features service.

The service is deliberately a thin proxy.  Lantmäteriet owns the land-cover
classification and its attributes, so callers receive the selected feature's
identifier and properties unchanged instead of a brittle local mapping.
"""

from base64 import b64encode
from hashlib import sha256
import json
import time
from typing import Any, Callable

from django.conf import settings
from django.core.cache import cache

from tempus.services import geo

_MISSING = object()


def _cache_singleflight(cache_key: str, timeout: int, fetch: Callable[[], Any]) -> Any:
    """Fetch-and-cache, but coalesce concurrent identical requests into ONE
    live call instead of each independently missing the cache and hitting
    Lantmäteriet at once.

    Confirmed live: several requests for the exact same, already-cached-once
    Locale arrived within the same second and were 429'd — a classic
    thundering herd, not a cache-key mismatch (the underlying cache design
    was already correct; nothing here was expiring or being recomputed
    wastefully once populated). Each of those concurrent requests started
    before the first one finished and wrote its result to the cache, so all
    of them independently queried Lantmäteriet, and Lantmäteriet's own rate
    limit rejected several of them.

    `cache.add` is atomic (set-if-not-present) and used as a lock: the first
    caller to add the lock key wins the right to actually fetch; everyone
    else polls the real cache key briefly for that winner's result instead
    of fetching themselves. If the winner never finishes in time (crashed,
    slow, or errored — cache.add's own timeout expires the lock either way),
    a waiter fetches for itself rather than hanging forever.
    """
    cached = cache.get(cache_key, _MISSING)
    if cached is not _MISSING:
        return cached

    lock_key = f"{cache_key}:lock"
    if cache.add(lock_key, 1, timeout=30):
        try:
            result = fetch()
        except Exception:
            cache.delete(lock_key)
            raise
        cache.set(cache_key, result, timeout=timeout)
        cache.delete(lock_key)
        return result

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        cached = cache.get(cache_key, _MISSING)
        if cached is not _MISSING:
            return cached
        time.sleep(0.2)
    # The winner didn't finish (or its result already expired) within our
    # wait budget — fetch it ourselves rather than blocking indefinitely.
    # Still cache it: a slow winner does not mean every future request
    # should also pay for its own live fetch.
    result = fetch()
    cache.set(cache_key, result, timeout=timeout)
    return result


class LantmaterietConfigurationError(RuntimeError):
    """Raised when the Marktäcke Direct integration lacks credentials."""


class LantmaterietAPIError(RuntimeError):
    """Raised when Lantmäteriet cannot serve a valid response."""


class LantmaterietMapTooLargeError(LantmaterietAPIError):
    """Raised when a Locale would produce an unsafe number of map features."""


class LantmaterietRateLimitedError(LantmaterietAPIError):
    """Raised when Lantmäteriet throttles requests (HTTP 429)."""

    def __init__(self, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


# Marktäcke Direkt's collection IDs, hardcoded rather than discovered live on
# every request. Verified directly against
# https://api.lantmateriet.se/ogc-features/v1/marktacke/collections/ (2026):
# "markytor" (Markytor / land surfaces, ~3.67M objects) and "sankmarksytor"
# (Sankmarksytor / wetland surfaces, ~1.45M objects) — NOT "sankmark", a
# wrong guess made without checking the live response first that broke the
# point-lookup and map endpoints (502s) until corrected here.
# `_discover_collections` (below) still exists for the rare case
# Lantmäteriet's offering actually changes — call it manually to verify and
# update this tuple, rather than paying for a live lookup on every request.
DEFAULT_COLLECTION_IDS: tuple[str, ...] = ("markytor", "sankmarksytor")


def _raise_for_status(response: Any, service_name: str) -> None:
    """Translate a non-OK Lantmäteriet response, honouring 429 Retry-After."""
    if response.ok:
        return
    if response.status_code == 429:
        retry_after = None
        header_value = response.headers.get("Retry-After")
        if header_value is not None:
            try:
                retry_after = int(float(header_value))
            except ValueError:
                retry_after = None
        raise LantmaterietRateLimitedError(
            f"Lantmäteriet {service_name} is rate limiting requests.",
            retry_after=retry_after,
        )
    raise LantmaterietAPIError(
        f"Lantmäteriet {service_name} returned HTTP {response.status_code}."
    )


def _config() -> dict[str, Any]:
    return getattr(settings, "LANTMATERIET_MARKTACKE", {}) or {}


def _authorization_header(config: dict[str, Any] | None = None) -> str:
    """Return static-token or Basic authentication.

    Private Geotorget customers use Basic authentication with their Geotorget
    credentials — confirmed sufficient on its own by Lantmäteriet's own
    documentation ("Bli konsument som privatperson": private individuals get
    Basic auth only, no OAuth option). ``ACCESS_TOKEN`` covers a manually
    obtained bearer token for accounts that have one.

    An OAuth2 client-credentials branch (``TOKEN_URL``/``CLIENT_ID``/
    ``CLIENT_SECRET``) used to live here. Removed 2026-09-17: it was never
    exercised against a real token endpoint in this codebase, Lantmäteriet
    documents Basic as a complete standalone method (not just a fallback) for
    exactly the private/Geotorget-account setup this project uses, and the
    branch's OAuth token cache key was hardcoded and shared across every
    Lantmäteriet product - a latent collision waiting for a second provider
    (e.g. Trafikverket) to reuse this function. If OAuth is needed later,
    reintroduce it deliberately, verified against a real token endpoint, with
    a cache key scoped to the specific config/provider it belongs to.
    """
    config = config or _config()
    static_token = config.get("ACCESS_TOKEN")
    if static_token:
        return f"Bearer {static_token}"

    username = config.get("USERNAME")
    password = config.get("PASSWORD")
    if username and password:
        credentials = b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        return f"Basic {credentials}"

    raise LantmaterietConfigurationError(
        "Configure LANTMATERIET_MARKTACKE_USERNAME and "
        "LANTMATERIET_MARKTACKE_PASSWORD for Basic authentication, or "
        "configure an API Portal access token."
    )


# Point clicks are never pixel-exact — moving the cursor a few pixels
# changes longitude/latitude slightly, and land-cover parcels are far
# larger than this grid, so snapping the query point itself to a ~30-50m
# grid before caching (and before querying) means nearby clicks share one
# cache entry and one real answer instead of each being treated as a
# distinct point that always misses the cache. Confirmed this endpoint had
# NO caching at all before this — every single click, however close to a
# previous one, was a live Lantmäteriet request.
_POINT_LOOKUP_GRID_DEGREES = 0.0005


def land_cover_at_point(longitude: float, latitude: float) -> dict[str, Any] | None:
    """Return land-cover and wetland features intersecting a WGS 84 point.

    Collection identifiers default to DEFAULT_COLLECTION_IDS unless an
    explicit allow-list is configured. The OGC API's CRS84 bbox lets the
    Locale endpoint use ordinary GeoJSON longitude/latitude coordinates.
    """
    grid = _POINT_LOOKUP_GRID_DEGREES
    longitude = round(longitude / grid) * grid
    latitude = round(latitude / grid) * grid

    config = _config()
    base_url = str(config.get("BASE_URL", "")).rstrip("/")
    if not base_url:
        raise LantmaterietConfigurationError(
            "Configure LANTMATERIET_MARKTACKE_BASE_URL."
        )

    cache_key = f"lantmateriet-point:{sha256(f'{longitude:.6f},{latitude:.6f}'.encode('utf-8')).hexdigest()}"

    def _fetch() -> dict[str, Any] | None:
        import requests

        headers = {
            "Accept": "application/geo+json, application/json",
            "Authorization": _authorization_header(),
        }
        collections = config.get("COLLECTION_IDS") or DEFAULT_COLLECTION_IDS
        params = {
            "f": "json",
            "bbox": f"{longitude},{latitude},{longitude},{latitude}",
            "bbox-crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
            "limit": 10,
        }
        features_at_point = []
        land_cover = None
        wetland = None
        for collection_id in collections:
            url = f"{base_url}/collections/{collection_id}/items"
            try:
                response = requests.get(
                    url, headers=headers, params=params, timeout=config.get("TIMEOUT", 15)
                )
            except requests.RequestException as exc:
                raise LantmaterietAPIError("Could not reach Lantmäteriet Marktäcke Direkt.") from exc
            _raise_for_status(response, "Marktäcke Direkt")

            try:
                payload = response.json()
            except ValueError as exc:
                raise LantmaterietAPIError(
                    "Lantmäteriet Marktäcke Direkt returned invalid JSON."
                ) from exc
            for feature in payload.get("features") or []:
                if not isinstance(feature, dict):
                    continue
                record = {
                    "collection": collection_id,
                    "feature_id": feature.get("id"),
                    "properties": feature.get("properties") or {},
                }
                features_at_point.append(record)
                if _is_wetland(record):
                    wetland = wetland or record
                else:
                    land_cover = land_cover or record

        if not features_at_point:
            return None
        return {
            "land_cover": land_cover,
            "wetland": wetland,
            "features": features_at_point,
        }

    return _cache_singleflight(cache_key, config.get("MAP_CACHE_SECONDS", 60 * 60 * 24 * 30), _fetch)


def land_cover_map(
    locale_geometry: dict[str, Any],
    *,
    simplify_tolerance: float | None = None,
    kinds: set[str] | None = None,
) -> dict[str, Any]:
    """Return all land-cover surfaces clipped exactly to a Locale geometry.

    OGC API Features' ``bbox`` query limits the upstream transfer. Shapely then
    intersects each returned surface with the actual Locale MultiPolygon, so
    the frontend never receives geometry beyond the Locale boundary.

    ``simplify_tolerance``, when given, generalises each clipped surface
    (in degrees) so a zoomed-out viewport transfers a reasonable amount of
    data instead of full-resolution geometry it cannot usefully render.

    ``kinds``, when given as a subset of ``{"land_cover", "wetland"}``, skips
    querying collections that cannot match: verified against the live
    account, wetland surfaces only ever come from the "sankmarksytor" collection
    (10,000+ sampled markytor features across a wide area contained no
    Sankmark objekttyp), so a ``kinds={"wetland"}`` request has no reason to
    fetch the much larger general land-cover collection at all. Per-feature
    ``_is_wetland`` classification still runs below regardless, as a
    correctness safety net.
    """
    try:
        from shapely.geometry import mapping, shape
    except ImportError as exc:
        raise LantmaterietConfigurationError(
            "Shapely is required for clipped land-cover map geometry."
        ) from exc

    try:
        locale_shape = shape(locale_geometry)
    except (TypeError, ValueError, KeyError) as exc:
        raise LantmaterietAPIError("Locale geometry is not valid GeoJSON.") from exc
    if locale_shape.is_empty:
        return {"type": "FeatureCollection", "features": []}

    config = _config()
    base_url = str(config.get("BASE_URL", "")).rstrip("/")
    if not base_url:
        raise LantmaterietConfigurationError(
            "Configure LANTMATERIET_MARKTACKE_BASE_URL."
        )

    headers = {
        "Accept": "application/geo+json, application/json",
        "Authorization": _authorization_header(),
    }
    collections = config.get("COLLECTION_IDS") or DEFAULT_COLLECTION_IDS
    if kinds is not None:
        collections = tuple(
            collection_id
            for collection_id in collections
            if ("wetland" in kinds and _is_wetland_collection(collection_id))
            or ("land_cover" in kinds and not _is_wetland_collection(collection_id))
        )
    cache_key = _map_cache_key(locale_geometry, collections, simplify_tolerance)

    # Marktäcke Direkt is a maintained but infrequently-updated survey
    # product, not real-time data, and Lantmäteriet is separately
    # rate-limited (see LantmaterietRateLimitedError) — a long cache
    # lifetime both matches how often the underlying data actually changes
    # and reduces how often repeat requests exercise that rate limit.
    # ~30 days by default, same reasoning as corine.py's
    # CORINE_LAND_COVER["CACHE_SECONDS"]; override MAP_CACHE_SECONDS per
    # environment for a shorter lifetime on a shared cache. This (and the
    # other MAP_CACHE_SECONDS uses below) is separate from the OAuth access
    # token cache above (see _authorization_header), which stays short and
    # tied to the token's own real expiry.
    #
    # Wrapped in _cache_singleflight, not a plain cache.get/set: confirmed
    # live, several requests for the exact same (already cacheable) Locale
    # arrived within the same second and were 429'd, because each one
    # independently missed the cache before the first had finished writing
    # to it. Singleflight ensures only one of those concurrent requests
    # actually calls Lantmäteriet; the rest wait for its result.
    def _fetch() -> dict[str, Any]:
        min_lon, min_lat, max_lon, max_lat = locale_shape.bounds
        features = []
        for collection_id in collections:
            for upstream_feature in _collection_features_in_bbox(
                base_url=base_url,
                collection_id=collection_id,
                headers=headers,
                config=config,
                bbox=(min_lon, min_lat, max_lon, max_lat),
            ):
                raw_geometry = upstream_feature.get("geometry")
                if not isinstance(raw_geometry, dict):
                    continue
                try:
                    clipped = shape(raw_geometry).intersection(locale_shape)
                except (TypeError, ValueError, KeyError) as exc:
                    raise LantmaterietAPIError(
                        "Lantmäteriet returned an invalid feature geometry."
                    ) from exc
                if clipped.is_empty:
                    continue
                if simplify_tolerance:
                    clipped = clipped.simplify(simplify_tolerance, preserve_topology=True)
                    if clipped.is_empty:
                        continue

                record = {
                    "collection": collection_id,
                    "feature_id": upstream_feature.get("id"),
                    "properties": upstream_feature.get("properties") or {},
                }
                features.append(
                    {
                        **record,
                        "kind": "wetland" if _is_wetland(record) else "land_cover",
                        "geometry": mapping(clipped),
                    }
                )
        return {"type": "FeatureCollection", "features": features}

    return _cache_singleflight(cache_key, config.get("MAP_CACHE_SECONDS", 60 * 60 * 24 * 30), _fetch)


def land_cover_in_bbox(
    bbox: tuple[float, float, float, float], *, kinds: set[str] | None = None
) -> dict[str, Any]:
    """Return land-cover surfaces for a map viewport, generalised when zoomed out."""
    try:
        from shapely.geometry import box, mapping
    except ImportError as exc:
        raise LantmaterietConfigurationError(
            "Shapely is required for clipped land-cover map geometry."
        ) from exc
    config = _config()
    _reject_oversized_bbox(bbox, config)
    tolerance = _simplify_tolerance_for_bbox(bbox, config)
    return land_cover_map(mapping(box(*bbox)), simplify_tolerance=tolerance, kinds=kinds)


def _objekttyp_in_filter(values: tuple[str, ...]) -> str:
    """Build a CQL2-text ``objekttyp IN (...)`` filter, single-quote-escaped.

    Verified live against the real service: Marktäcke Direkt's OGC API
    supports CQL2 ``IN`` filtering on ``objekttyp`` (exact match, not
    CASEI/LIKE — confirmed the property is queried case-sensitively and
    without wildcards elsewhere, e.g. _SUMMARY_FILTER above), and applying it
    server-side returned only the requested types instead of the caller
    downloading every surface in the bbox and filtering locally.
    """
    quoted = ", ".join("'" + value.replace("'", "''") + "'" for value in values)
    return f"objekttyp IN ({quoted})"


def land_cover_by_types_in_bbox(
    bbox: tuple[float, float, float, float],
    objekttyp_values: tuple[str, ...],
    *,
    kinds: set[str] | None = None,
) -> dict[str, Any]:
    """Return only the requested ``objekttyp`` surfaces for a map viewport.

    Filters server-side via CQL2 (see ``_objekttyp_in_filter``), so callers
    asking for a narrow selection (e.g. just "Barr- och blandskog") never
    pay for downloading and discarding every other surface in the bbox.
    Subject to the same viewport size limit as the full-detail layer (see
    ``_reject_oversized_bbox``) since, like it, this returns full-resolution
    per-surface geometry rather than a generalised overview.
    """
    try:
        from shapely.geometry import box, mapping, shape
    except ImportError as exc:
        raise LantmaterietConfigurationError(
            "Shapely is required for clipped land-cover map geometry."
        ) from exc

    if not objekttyp_values:
        raise LantmaterietAPIError("At least one objekttyp value must be requested.")

    config = _config()
    _reject_oversized_bbox(bbox, config)
    base_url = str(config.get("BASE_URL", "")).rstrip("/")
    if not base_url:
        raise LantmaterietConfigurationError("Configure LANTMATERIET_MARKTACKE_BASE_URL.")

    headers = {
        "Accept": "application/geo+json, application/json",
        "Authorization": _authorization_header(config),
    }
    collections = config.get("COLLECTION_IDS") or DEFAULT_COLLECTION_IDS
    if kinds is not None:
        collections = tuple(
            collection_id
            for collection_id in collections
            if ("wetland" in kinds and _is_wetland_collection(collection_id))
            or ("land_cover" in kinds and not _is_wetland_collection(collection_id))
        )
    filter_expr = _objekttyp_in_filter(tuple(objekttyp_values))
    cache_key = _map_cache_key(
        {"bbox": bbox, "objekttyp": tuple(sorted(objekttyp_values))}, collections, None
    )

    def _fetch() -> dict[str, Any]:
        clip_shape = box(*bbox)
        tolerance = _simplify_tolerance_for_bbox(bbox, config)
        features = []
        for collection_id in collections:
            for upstream_feature in _collection_features_in_bbox(
                base_url=base_url,
                collection_id=collection_id,
                headers=headers,
                config=config,
                bbox=bbox,
                filter_expr=filter_expr,
            ):
                raw_geometry = upstream_feature.get("geometry")
                if not isinstance(raw_geometry, dict):
                    continue
                try:
                    clipped = shape(raw_geometry).intersection(clip_shape)
                except (TypeError, ValueError, KeyError) as exc:
                    raise LantmaterietAPIError(
                        "Lantmäteriet returned an invalid feature geometry."
                    ) from exc
                if clipped.is_empty:
                    continue
                if tolerance:
                    clipped = clipped.simplify(tolerance, preserve_topology=True)
                    if clipped.is_empty:
                        continue

                record = {
                    "collection": collection_id,
                    "feature_id": upstream_feature.get("id"),
                    "properties": upstream_feature.get("properties") or {},
                }
                features.append(
                    {
                        **record,
                        "kind": "wetland" if _is_wetland(record) else "land_cover",
                        "geometry": mapping(clipped),
                    }
                )
        return {"type": "FeatureCollection", "features": features}

    return _cache_singleflight(cache_key, config.get("MAP_CACHE_SECONDS", 60 * 60 * 24 * 30), _fetch)


def buffered_bbox(
    geometry: dict[str, Any], buffer_metres: float
) -> tuple[float, float, float, float]:
    """Expand a GeoJSON geometry's bounding box by ``buffer_metres`` in every direction.

    Takes a plain geometry rather than a Locale, so callers who need a padded
    area for some other geometry later are not tied to the Locale model.
    Uses a simple equirectangular approximation (matching the degree-based
    limits elsewhere in this module, e.g. ``_reject_oversized_bbox``) rather
    than a projected buffer - accurate enough for a padding distance, not for
    precise area calculations.
    """
    from math import cos, radians

    from shapely.geometry import shape

    try:
        min_lon, min_lat, max_lon, max_lat = shape(geometry).bounds
    except (TypeError, ValueError, KeyError) as exc:
        raise LantmaterietAPIError("Geometry is not valid GeoJSON.") from exc

    lat_pad = buffer_metres / 111_320
    lon_pad = buffer_metres / (111_320 * max(cos(radians((min_lat + max_lat) / 2)), 0.01))
    return (min_lon - lon_pad, min_lat - lat_pad, max_lon + lon_pad, max_lat + lat_pad)


def map_for_area(
    fetch_fn: Callable[[dict[str, Any]], dict[str, Any]],
    geometry: dict[str, Any],
    buffer_metres: float,
) -> dict[str, Any]:
    """Pad ``geometry`` by ``buffer_metres`` and call ``fetch_fn`` with the result.

    One generic helper instead of a dedicated ``<source>_map_for_area``
    function per product (an earlier version of this file had
    ``land_cover_map_for_area``/``hydrography_map_for_area``/
    ``buildings_map_for_area``, each repeating the same three lines - removed
    2026-09-18 as the exact kind of per-layer duplication this exists to
    avoid). ``fetch_fn`` is any geometry-clipping function (``land_cover_map``,
    ``hydrography_map``, or a future source's equivalent) - not tied to
    Locale, any GeoJSON geometry works. ``tasks.fetch_locale_land_cover``
    already computes the padded geometry once and shares it across every
    source rather than calling this per source.
    """
    from shapely.geometry import box, mapping

    bbox = buffered_bbox(geometry, buffer_metres)
    return fetch_fn(mapping(box(*bbox)))


_SUMMARY_FILTER = "CASEI(objekttyp) LIKE '%skog%' OR CASEI(objekttyp) LIKE '%åker%'"


def land_cover_summary_in_bbox(bbox: tuple[float, float, float, float]) -> dict[str, Any]:
    """Return only forest and arable-land surfaces for a wide map viewport.

    Lantmäteriet is asked to filter by ``objekttyp`` (CQL2) before anything is
    transferred, so a zoomed-out viewport that cannot use the full land-cover
    layer still gets a real, bounded overview instead of nothing. This is
    also the fallback when the full layer's request fails or is rejected as
    too large: coarser data beats no data.
    """
    try:
        from shapely.geometry import box, mapping, shape
    except ImportError as exc:
        raise LantmaterietConfigurationError(
            "Shapely is required for clipped land-cover map geometry."
        ) from exc

    config = _config()
    min_lon, min_lat, max_lon, max_lat = bbox
    width = max(max_lon - min_lon, max_lat - min_lat)
    max_width = config.get("MAP_SUMMARY_MAX_BBOX_DEGREES", 0.5)  # ~55 km
    if width > max_width:
        raise LantmaterietMapTooLargeError(
            "The requested map area is too large even for the forest/agriculture overview."
        )

    base_url = str(config.get("BASE_URL", "")).rstrip("/")
    if not base_url:
        raise LantmaterietConfigurationError("Configure LANTMATERIET_MARKTACKE_BASE_URL.")

    headers = {
        "Accept": "application/geo+json, application/json",
        "Authorization": _authorization_header(config),
    }
    cache_key = _map_cache_key(
        {"bbox": bbox}, ("markytor:forest-agriculture",), None
    )

    def _fetch() -> dict[str, Any]:
        clip_shape = box(*bbox)
        tolerance = _simplify_tolerance_for_bbox(bbox, config)
        features = []
        for upstream_feature in _collection_features_in_bbox(
            base_url=base_url,
            collection_id="markytor",
            headers=headers,
            config=config,
            bbox=bbox,
            filter_expr=_SUMMARY_FILTER,
        ):
            raw_geometry = upstream_feature.get("geometry")
            if not isinstance(raw_geometry, dict):
                continue
            try:
                clipped = shape(raw_geometry).intersection(clip_shape)
            except (TypeError, ValueError, KeyError) as exc:
                raise LantmaterietAPIError(
                    "Lantmäteriet returned an invalid feature geometry."
                ) from exc
            if clipped.is_empty:
                continue
            if tolerance:
                clipped = clipped.simplify(tolerance, preserve_topology=True)
                if clipped.is_empty:
                    continue

            properties = upstream_feature.get("properties") or {}
            objekttyp = str(properties.get("objekttyp", "")).casefold()
            group = "forest" if "skog" in objekttyp else "agriculture"
            features.append(
                {
                    "collection": "markytor",
                    "feature_id": upstream_feature.get("id"),
                    "properties": properties,
                    "kind": "land_cover",
                    "objekttyp_group": group,
                    "geometry": mapping(clipped),
                }
            )
        return {"type": "FeatureCollection", "features": features}

    return _cache_singleflight(cache_key, config.get("MAP_CACHE_SECONDS", 60 * 60 * 24 * 30), _fetch)


def land_cover_overview_in_bbox(bbox: tuple[float, float, float, float]) -> dict[str, Any]:
    """Return one dissolved, heavily generalised shape per forest/agriculture.

    For a region- or country-scale viewport, even the per-surface summary is
    too much to transfer and render. This still asks Lantmäteriet to filter
    by ``objekttyp`` server-side, but then merges every returned surface per
    group into a single polygon and simplifies it hard, so the response is a
    small, fixed number of features regardless of how much upstream detail
    exists underneath.
    """
    try:
        from shapely.geometry import box, mapping, shape
        from shapely.ops import unary_union
    except ImportError as exc:
        raise LantmaterietConfigurationError(
            "Shapely is required for clipped land-cover map geometry."
        ) from exc

    config = _config()
    min_lon, min_lat, max_lon, max_lat = bbox
    width = max(max_lon - min_lon, max_lat - min_lat)
    max_width = config.get("MAP_OVERVIEW_MAX_BBOX_DEGREES", 6.0)  # roughly all of Sweden
    if width > max_width:
        raise LantmaterietMapTooLargeError(
            "The requested map area is too large even for the generalised overview."
        )

    base_url = str(config.get("BASE_URL", "")).rstrip("/")
    if not base_url:
        raise LantmaterietConfigurationError("Configure LANTMATERIET_MARKTACKE_BASE_URL.")

    headers = {
        "Accept": "application/geo+json, application/json",
        "Authorization": _authorization_header(config),
    }
    cache_key = _map_cache_key({"bbox": bbox}, ("markytor:overview",), None)

    def _fetch() -> dict[str, Any]:
        overview_config = {
            **config,
            "MAP_MAX_FEATURES": config.get("MAP_OVERVIEW_MAX_FEATURES", 50000),
        }
        clip_shape = box(*bbox)
        tolerance = config.get("MAP_OVERVIEW_SIMPLIFY_TOLERANCE", 0.02)  # ~2 km
        shapes_by_group: dict[str, list[Any]] = {"forest": [], "agriculture": []}
        for upstream_feature in _collection_features_in_bbox(
            base_url=base_url,
            collection_id="markytor",
            headers=headers,
            config=overview_config,
            bbox=bbox,
            filter_expr=_SUMMARY_FILTER,
        ):
            raw_geometry = upstream_feature.get("geometry")
            if not isinstance(raw_geometry, dict):
                continue
            try:
                clipped = shape(raw_geometry).intersection(clip_shape)
            except (TypeError, ValueError, KeyError) as exc:
                raise LantmaterietAPIError(
                    "Lantmäteriet returned an invalid feature geometry."
                ) from exc
            if clipped.is_empty:
                continue
            objekttyp = str((upstream_feature.get("properties") or {}).get("objekttyp", "")).casefold()
            group = "forest" if "skog" in objekttyp else "agriculture"
            shapes_by_group[group].append(clipped)

        features = []
        for group, shapes in shapes_by_group.items():
            if not shapes:
                continue
            merged = unary_union(shapes).simplify(tolerance, preserve_topology=True)
            if merged.is_empty:
                continue
            features.append(
                {
                    "collection": "markytor",
                    "feature_id": None,
                    "properties": {},
                    "kind": "land_cover",
                    "objekttyp_group": group,
                    "geometry": mapping(merged),
                }
            )
        return {"type": "FeatureCollection", "features": features}

    return _cache_singleflight(cache_key, config.get("MAP_CACHE_SECONDS", 60 * 60 * 24 * 30), _fetch)


def _reject_oversized_bbox(
    bbox: tuple[float, float, float, float], config: dict[str, Any]
) -> None:
    """Refuse a viewport too large to fetch, before any request leaves for Lantmäteriet.

    Simplifying geometry after the fact still means downloading Lantmäteriet's
    full-resolution data for the whole viewport first. A zoomed-out viewport
    over a large region must instead be rejected up front so the frontend asks
    the user to zoom in, rather than pulling and discarding most of the detail.
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    width = max(max_lon - min_lon, max_lat - min_lat)
    max_width = config.get("MAP_MAX_BBOX_DEGREES", 0.045)  # ~5 km
    if width > max_width:
        raise LantmaterietMapTooLargeError(
            "The requested map area is too large; zoom in before loading land cover."
        )


def _simplify_tolerance_for_bbox(
    bbox: tuple[float, float, float, float], config: dict[str, Any]
) -> float | None:
    """Scale geometry detail down as a viewport bbox grows.

    A tightly zoomed-in bbox keeps full Lantmäteriet resolution. A wide,
    zoomed-out bbox would otherwise transfer far more coastline and surface
    detail than the viewport can render, so it is generalised proportionally
    to its width, capped at a configurable maximum.
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    width = max(max_lon - min_lon, max_lat - min_lat)
    divisor = config.get("MAP_SIMPLIFY_DIVISOR", 1500)
    max_tolerance = config.get("MAP_SIMPLIFY_MAX_TOLERANCE", 0.01)
    tolerance = width / divisor
    if tolerance <= 0:
        return None
    return min(tolerance, max_tolerance)


def administrative_boundaries(locale_geometry: dict[str, Any]) -> dict[str, Any]:
    """Return OAPIF administrative surfaces clipped to a GeoJSON geometry."""
    return _administrative_boundaries_for_geometry(locale_geometry)


def administrative_boundaries_in_bbox(
    bbox: tuple[float, float, float, float]
) -> dict[str, Any]:
    """Return administrative boundaries for a map viewport, clipped to its bbox.

    A country-scale viewport must stay renderable, so it is never rejected
    like the land-cover layer: instead, detail scales down with the bbox.
    Municipality outlines (~290 of them) only make sense once the viewport is
    reasonably close; at wider zoom only counties, then only the country
    outline, are returned, and geometry is simplified proportionally to bbox
    width throughout.
    """
    try:
        from shapely.geometry import box, mapping
    except ImportError as exc:
        raise LantmaterietConfigurationError(
            "Shapely is required for administrative boundary geometry."
        ) from exc
    config = _administrative_config()
    kinds = _administrative_kinds_for_bbox(bbox, config)
    tolerance = _administrative_simplify_tolerance_for_bbox(bbox, config)
    return _administrative_boundaries_for_geometry(
        mapping(box(*bbox)), kinds=kinds, simplify_tolerance=tolerance
    )


def _administrative_kinds_for_bbox(
    bbox: tuple[float, float, float, float], config: dict[str, Any]
) -> set[str] | None:
    """Drop finer administrative levels as the viewport widens.

    Returns ``None`` (no filtering) when the full set, including
    municipalities, is appropriate.
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    width = max(max_lon - min_lon, max_lat - min_lat)
    municipality_max = config.get("MAP_MUNICIPALITY_MAX_BBOX_DEGREES", 2.0)
    county_max = config.get("MAP_COUNTY_MAX_BBOX_DEGREES", 6.0)
    if width <= municipality_max:
        return None
    if width <= county_max:
        return {"county", "country"}
    return {"country"}


def _administrative_simplify_tolerance_for_bbox(
    bbox: tuple[float, float, float, float], config: dict[str, Any]
) -> float | None:
    """Scale administrative-boundary detail down as the viewport widens.

    Uses its own divisor/cap from land cover's: municipality/county outlines
    are already far simpler shapes than land-cover surfaces, so they need
    less aggressive generalisation to stay renderable at whole-country scale.
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    width = max(max_lon - min_lon, max_lat - min_lat)
    divisor = config.get("MAP_SIMPLIFY_DIVISOR", 800)
    max_tolerance = config.get("MAP_SIMPLIFY_MAX_TOLERANCE", 0.02)
    tolerance = width / divisor
    if tolerance <= 0:
        return None
    return min(tolerance, max_tolerance)


def _administrative_boundaries_for_geometry(
    clip_geometry: dict[str, Any],
    *,
    kinds: set[str] | None = None,
    simplify_tolerance: float | None = None,
) -> dict[str, Any]:
    try:
        from shapely.geometry import mapping, shape
    except ImportError as exc:
        raise LantmaterietConfigurationError(
            "Shapely is required for administrative boundary geometry."
        ) from exc

    try:
        clip_shape = shape(clip_geometry)
    except (TypeError, ValueError, KeyError) as exc:
        raise LantmaterietAPIError("Map geometry is not valid GeoJSON.") from exc
    if clip_shape.is_empty:
        return {"type": "FeatureCollection", "features": []}

    config = _administrative_config()
    base_url = str(config.get("BASE_URL", "")).rstrip("/")
    if not base_url:
        raise LantmaterietConfigurationError(
            "Configure LANTMATERIET_ADMINISTRATIVE_BOUNDARIES_BASE_URL."
        )
    headers = {
        "Accept": "application/geo+json, application/json",
        # Kommun, Län och Rike Direkt uses the same Geotorget credentials as
        # Marktäcke; LANTMATERIET_ADMINISTRATIVE_BOUNDARIES has no auth keys
        # of its own by design (see settings.py).
        "Authorization": _authorization_header(),
    }
    collections = _discover_administrative_collections(base_url, headers, config)
    if kinds is not None:
        collections = {
            kind: collection_id
            for kind, collection_id in collections.items()
            if kind in kinds
        }
    if not collections:
        return {"type": "FeatureCollection", "features": []}

    cache_key = _administrative_cache_key(
        clip_geometry, tuple(collections.items()), simplify_tolerance
    )

    # Singleflight for the same reason as land_cover_map above: confirmed
    # live, concurrent requests for the same Locale's administrative
    # boundaries were also racing each other and getting 429'd by
    # Lantmäteriet before the first request finished populating the cache.
    def _fetch() -> dict[str, Any]:
        features = []
        for kind, collection_id in collections.items():
            for upstream_feature in _collection_features_in_bbox(
                base_url=base_url,
                collection_id=collection_id,
                headers=headers,
                config=config,
                bbox=clip_shape.bounds,
                service_name="Kommun, Län och Rike Direkt",
            ):
                raw_geometry = upstream_feature.get("geometry")
                if not isinstance(raw_geometry, dict):
                    continue
                try:
                    clipped = shape(raw_geometry).intersection(clip_shape)
                except (TypeError, ValueError, KeyError) as exc:
                    raise LantmaterietAPIError(
                        "Lantmäteriet returned an invalid administrative geometry."
                    ) from exc
                if clipped.is_empty:
                    continue
                if simplify_tolerance:
                    clipped = clipped.simplify(simplify_tolerance, preserve_topology=True)
                    if clipped.is_empty:
                        continue
                features.append(
                    {
                        "collection": collection_id,
                        "feature_id": upstream_feature.get("id"),
                        "kind": kind,
                        "properties": upstream_feature.get("properties") or {},
                        "geometry": mapping(clipped),
                    }
                )
        return {"type": "FeatureCollection", "features": features}

    return _cache_singleflight(cache_key, config.get("MAP_CACHE_SECONDS", 60 * 60 * 24 * 30), _fetch)


def _collection_features_in_bbox(
    *,
    base_url: str,
    collection_id: str,
    headers: dict[str, str],
    config: dict[str, Any],
    bbox: tuple[float, float, float, float],
    service_name: str = "Marktäcke Direkt",
    filter_expr: str | None = None,
) -> list[dict[str, Any]]:
    """Retrieve every page of one collection intersecting a WGS 84 bbox.

    ``filter_expr``, when given, is sent as a CQL2-text ``filter`` so
    Lantmäteriet narrows the result server-side (e.g. by ``objekttyp``)
    instead of us downloading everything and discarding most of it locally.
    """
    import requests

    url = f"{base_url}/collections/{collection_id}/items"
    params: dict[str, Any] | None = {
        "f": "json",
        "bbox": ",".join(str(value) for value in bbox),
        "bbox-crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
        "limit": config.get("MAP_PAGE_SIZE", 1000),
    }
    if filter_expr:
        params["filter"] = filter_expr
        params["filter-lang"] = "cql2-text"
    results = []
    max_features = config.get("MAP_MAX_FEATURES", 10000)

    while url:
        try:
            response = requests.get(
                url, headers=headers, params=params, timeout=config.get("TIMEOUT", 15)
            )
        except requests.RequestException as exc:
            raise LantmaterietAPIError(f"Could not reach Lantmäteriet {service_name}.") from exc
        _raise_for_status(response, service_name)
        try:
            payload = response.json()
        except ValueError as exc:
            raise LantmaterietAPIError(
                f"Lantmäteriet {service_name} returned invalid JSON."
            ) from exc

        results.extend(
            feature
            for feature in payload.get("features") or []
            if isinstance(feature, dict)
        )
        if len(results) > max_features:
            raise LantmaterietMapTooLargeError(
                f"The requested map area contains too many {service_name} features to render in one response."
            )
        url = _next_page_url(payload, base_url)
        params = None
    return results


def _next_page_url(payload: dict[str, Any], base_url: str) -> str | None:
    """Return a trusted upstream pagination link, if present."""
    from urllib.parse import urljoin, urlparse

    base = urlparse(base_url)
    for link in payload.get("links") or []:
        if not isinstance(link, dict) or link.get("rel") != "next":
            continue
        href = link.get("href")
        if not isinstance(href, str):
            continue
        next_url = urljoin(f"{base_url}/", href)
        parsed = urlparse(next_url)
        if parsed.scheme == base.scheme and parsed.netloc == base.netloc:
            return next_url
    return None


def _map_cache_key(
    locale_geometry: dict[str, Any],
    collections: tuple[str, ...],
    simplify_tolerance: float | None = None,
) -> str:
    encoded = json.dumps(
        {
            "geometry": locale_geometry,
            "collections": collections,
            "simplify_tolerance": simplify_tolerance,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"lantmateriet-marktacke-map:{sha256(encoded).hexdigest()}"


def _administrative_config() -> dict[str, Any]:
    return getattr(settings, "LANTMATERIET_ADMINISTRATIVE_BOUNDARIES", {}) or {}


def _administrative_cache_key(
    locale_geometry: dict[str, Any],
    collections: tuple[tuple[str, str], ...],
    simplify_tolerance: float | None = None,
) -> str:
    encoded = json.dumps(
        {
            "geometry": locale_geometry,
            "collections": collections,
            "simplify_tolerance": simplify_tolerance,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"lantmateriet-administrative-boundaries:{sha256(encoded).hexdigest()}"


def _discover_administrative_collections(
    base_url: str, headers: dict[str, str], config: dict[str, Any]
) -> dict[str, str]:
    """Find the OAPIF collections for municipality, county, and country.

    Cached the same way as _discover_collections above and for the same
    reason: this was called live on every single administrative-boundaries
    request, unconditionally, before that request's own cache_key/cache.get
    check even ran — regardless of how long the eventual result was cached
    for. Confirmed live: this was a second, independent instance of the same
    bug class as _discover_collections, and a direct contributor to
    Lantmäteriet's rate limit being hit on repeated requests for the same
    Locale. Kommun/Län/Rike Direkt's yearly-dated collections (see
    _current_administrative_collection_id) mean this result can change once
    a year at most, so the same long lifetime as the map responses
    (MAP_CACHE_SECONDS) is appropriate here too.
    """
    import requests

    cache_key = f"lantmateriet-admin-collections:{sha256(base_url.encode('utf-8')).hexdigest()}"

    def _fetch() -> dict[str, str]:
        try:
            response = requests.get(
                f"{base_url}/collections",
                headers=headers,
                timeout=config.get("TIMEOUT", 30),
            )
        except requests.RequestException as exc:
            raise LantmaterietAPIError("Could not retrieve administrative-boundary collections.") from exc
        _raise_for_status(response, "administrative-boundary collections")
        try:
            payload = response.json()
        except ValueError as exc:
            raise LantmaterietAPIError(
                "Lantmäteriet administrative-boundary collections returned invalid JSON."
            ) from exc

        allowed_ids = set(config.get("COLLECTION_IDS") or ())
        candidates: dict[str, list[str]] = {}
        for item in payload.get("collections") or []:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                continue
            if allowed_ids and item["id"] not in allowed_ids:
                continue
            text = json.dumps(
                {key: item.get(key) for key in ("id", "title", "description")},
                ensure_ascii=False,
            ).casefold()
            kind = _administrative_kind(text)
            if kind:
                candidates.setdefault(kind, []).append(item["id"])
        if "country" not in candidates:
            raise LantmaterietAPIError(
                "No country collection is available in Kommun, Län och Rike Direkt for this account."
            )
        return {kind: _current_administrative_collection_id(ids) for kind, ids in candidates.items()}

    result = _cache_singleflight(cache_key, config.get("MAP_CACHE_SECONDS", 60 * 60 * 24 * 30), _fetch)
    return result


def _current_administrative_collection_id(ids: list[str]) -> str:
    """Pick the current, unversioned collection out of e.g. kommuner/
    kommuner-2025/kommuner-2026.

    Verified against the live account: each level lists an unversioned id
    alongside dated yearly editions (confirmed for kommuner, lan, and rike).
    Matching the id shape explicitly avoids depending on the API happening to
    list the unversioned one first.
    """
    import re

    undated = [item_id for item_id in ids if not re.search(r"-\d{4}$", item_id)]
    return undated[0] if undated else ids[0]


def _administrative_kind(source: str) -> str | None:
    if "kommun" in source:
        return "municipality"
    if "län" in source or "lan" in source:
        return "county"
    if "rike" in source or "sverige" in source:
        return "country"
    return None


def _is_wetland(feature: dict[str, Any]) -> bool:
    """Identify Lantmäteriet's Sankmark feature without changing its data."""
    collection = str(feature.get("collection", "")).casefold()
    properties = feature.get("properties") or {}
    if not isinstance(properties, dict):
        return "sankmark" in collection
    values = " ".join(str(value) for value in properties.values()).casefold()
    return "sankmark" in collection or "sankmark" in values


def _is_wetland_collection(collection_id: str) -> bool:
    """Identify a wetland-only collection (e.g. ``sankmarksytor``) by id."""
    return "sankmark" in collection_id.casefold()


def _discover_collections(
    base_url: str, headers: dict[str, str], config: dict[str, Any]
) -> tuple[str, ...]:
    """List the collections visible to the authenticated account.

    The product's collection names are service metadata, not stable local
    configuration. An optional COLLECTION_IDS value remains useful to restrict
    a deployment to selected subsets.

    Cached: this was previously called live on every single land_cover_map
    invocation — i.e. on every full-detail viewport request, since that is
    tried first — with no caching at all, regardless of how long the actual
    land-cover result for that bbox was cached for. Confirmed live: this was
    a real, previously-unnoticed source of Lantmäteriet API traffic hitting
    the rate limit independent of the land-cover response caching. Collection
    IDs are service metadata that essentially never change, so the same long
    lifetime as the map responses (MAP_CACHE_SECONDS) is used here too — not
    per-bbox, just once per base_url, since this call does not depend on the
    request's geometry at all.
    """
    import requests

    cache_key = f"lantmateriet-collections:{sha256(base_url.encode('utf-8')).hexdigest()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        response = requests.get(
            f"{base_url}/collections",
            headers=headers,
            params={"f": "json"},
            timeout=config.get("TIMEOUT", 15),
        )
    except requests.RequestException as exc:
        raise LantmaterietAPIError("Could not retrieve Lantmäteriet collections.") from exc
    _raise_for_status(response, "collections endpoint")
    try:
        payload = response.json()
    except ValueError as exc:
        raise LantmaterietAPIError(
            "Lantmäteriet collections endpoint returned invalid JSON."
        ) from exc
    collection_ids = tuple(
        item["id"]
        for item in payload.get("collections", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]
    )
    if not collection_ids:
        raise LantmaterietAPIError(
            "Lantmäteriet returned no land-cover collections for this account."
        )
    cache.set(cache_key, collection_ids, timeout=config.get("MAP_CACHE_SECONDS", 60 * 60 * 24 * 30))
    return collection_ids


# --- Hydrografi (lakes, watercourses, coastline) ---------------------------
#
# A separate Lantmäteriet OGC API Features product from Marktäcke Direkt
# above, with its own API root (LANTMATERIET_HYDROGRAFI) but the same
# Geotorget credentials - same pattern as LANTMATERIET_ADMINISTRATIVE_
# BOUNDARIES. Verified live against
# https://api.lantmateriet.se/ogc-features/v1/hydrografi/collections (2026):
# "StandingWater" (lakes, ~392k objects), "WatercourseLine"/
# "WatercoursePolygon" (rivers/streams, ~924k/~27k objects), and
# "LandWaterBoundary" (coastline as a LineString, ~1.85M objects). There is
# NO sea-surface polygon collection in this product - open sea is already
# covered by Marktäcke's own "markytor" "Hav" objekttyp (see land_cover_map
# above), confirmed live to come through unfiltered.
HYDROGRAFI_DEFAULT_COLLECTION_IDS: tuple[str, ...] = (
    "StandingWater",
    "WatercourseLine",
    "WatercoursePolygon",
    "LandWaterBoundary",
)

_HYDROGRAFI_KIND_BY_COLLECTION = {
    "StandingWater": "lake",
    "WatercourseLine": "watercourse",
    "WatercoursePolygon": "watercourse",
    "LandWaterBoundary": "coastline",
}


def _hydrografi_config() -> dict[str, Any]:
    return getattr(settings, "LANTMATERIET_HYDROGRAFI", {}) or {}


def _hydrografi_cache_key(
    geometry: dict[str, Any],
    collections: tuple[str, ...],
    simplify_tolerance: float | None = None,
) -> str:
    encoded = json.dumps(
        {"geometry": geometry, "collections": collections, "simplify_tolerance": simplify_tolerance},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"lantmateriet-hydrografi-map:{sha256(encoded).hexdigest()}"


def hydrography_map(
    geometry: dict[str, Any],
    *,
    simplify_tolerance: float | None = None,
    kinds: set[str] | None = None,
) -> dict[str, Any]:
    """Return lake, watercourse, and coastline features clipped exactly to a geometry.

    Same shape and clipping approach as ``land_cover_map`` (bbox-limited
    upstream fetch, then Shapely intersection against the exact geometry), for
    Hydrografi instead of Marktäcke Direkt. ``LandWaterBoundary`` features are
    lines, not polygons; intersecting a line against the clip polygon still
    works and yields the (Multi)LineString segment(s) inside it.

    ``kinds``, when given as a subset of ``{"lake", "watercourse",
    "coastline"}``, skips querying collections that cannot match.
    """
    try:
        from shapely.geometry import mapping, shape
    except ImportError as exc:
        raise LantmaterietConfigurationError(
            "Shapely is required for clipped hydrography geometry."
        ) from exc

    try:
        clip_shape = shape(geometry)
    except (TypeError, ValueError, KeyError) as exc:
        raise LantmaterietAPIError("Geometry is not valid GeoJSON.") from exc
    if clip_shape.is_empty:
        return {"type": "FeatureCollection", "features": []}

    config = _hydrografi_config()
    base_url = str(config.get("BASE_URL", "")).rstrip("/")
    if not base_url:
        raise LantmaterietConfigurationError("Configure LANTMATERIET_HYDROGRAFI_BASE_URL.")

    headers = {
        "Accept": "application/geo+json, application/json",
        # Reuses Marktäcke's Geotorget credentials, like
        # LANTMATERIET_ADMINISTRATIVE_BOUNDARIES does - confirmed live against
        # the Hydrografi API with the same Basic-auth account.
        "Authorization": _authorization_header(),
    }
    collections = config.get("COLLECTION_IDS") or HYDROGRAFI_DEFAULT_COLLECTION_IDS
    if kinds is not None:
        collections = tuple(
            collection_id
            for collection_id in collections
            if _HYDROGRAFI_KIND_BY_COLLECTION.get(collection_id) in kinds
        )
    cache_key = _hydrografi_cache_key(geometry, collections, simplify_tolerance)

    def _fetch() -> dict[str, Any]:
        min_lon, min_lat, max_lon, max_lat = clip_shape.bounds
        features = []
        for collection_id in collections:
            for upstream_feature in _collection_features_in_bbox(
                base_url=base_url,
                collection_id=collection_id,
                headers=headers,
                config=config,
                bbox=(min_lon, min_lat, max_lon, max_lat),
                service_name="Hydrografi",
            ):
                raw_geometry = upstream_feature.get("geometry")
                if not isinstance(raw_geometry, dict):
                    continue
                try:
                    clipped = shape(raw_geometry).intersection(clip_shape)
                except (TypeError, ValueError, KeyError) as exc:
                    raise LantmaterietAPIError(
                        "Lantmäteriet returned an invalid hydrography feature geometry."
                    ) from exc
                if clipped.is_empty:
                    continue
                if simplify_tolerance:
                    clipped = clipped.simplify(simplify_tolerance, preserve_topology=True)
                    if clipped.is_empty:
                        continue

                features.append(
                    {
                        "collection": collection_id,
                        "feature_id": upstream_feature.get("id"),
                        "kind": _HYDROGRAFI_KIND_BY_COLLECTION.get(collection_id, "other"),
                        "properties": upstream_feature.get("properties") or {},
                        "geometry": mapping(clipped),
                    }
                )
        return {"type": "FeatureCollection", "features": features}

    return _cache_singleflight(cache_key, config.get("MAP_CACHE_SECONDS", 60 * 60 * 24 * 30), _fetch)


# --- Ortnamn Direkt (place names) -------------------------------------------
#
# A separate Lantmäteriet REST API, NOT OGC API Features like the products
# above - its base path is "distribution/produkter/ortnamn/v2.2", not
# "ogc-features/v1/...".
#
# Confirmed live with real credentials (2026-09-18):
# - The current version is v2.2 (Geotorget's "Åtkomstpunkt"). The previous
#   default, v2.1, is the outgoing version: the same Basic credentials that
#   work on v2.2 get HTTP 401 "Missing Credentials" on v2.1 - the account's
#   product authorization is for the current version only.
# - Only SWEREF 99 reference systems are accepted, for input and output alike:
#   ``srid=4326``/``punktSrid=4326`` fail with 400 "Reference system not
#   supported: 4326". Requests therefore use EPSG:3006 and this module
#   converts to/from WGS 84 with ``geo.sweref99tm_to_wgs84``/
#   ``geo.wgs84_to_sweref99tm``.
# - ``punkt`` is ``"northing,easting"`` (N first) and may NOT be combined with
#   ``maxHits`` (400 "maxHits is not allowed with punkt").
# - The response is a GeoJSON FeatureCollection (top-level ``totaltAntal``)
#   whose features have ``geometry: null`` and everything under
#   ``properties``: ``id``, ``namn``, ``sprak`` and ``placering[]`` with
#   ``kommunkod``/``kommunnamn``/``lankod``/``lannamn``/``namntyp``/
#   ``sockenstadkod``/``sockenstadnamn`` and ``punkt`` (a GeoJSON Point in the
#   requested SRID). One name commonly has SEVERAL placements (e.g. "Stockholm"
#   returns three), so a feature here is one (name, placement) pair.
#
# There is NO bbox or radius parameter on this product: ``punkt`` returns
# only the single closest name, not every name within a distance or area.
# Unlike land_cover_in_bbox/hydrography_map, there is therefore no per-
# viewport map layer here - only a nearest-point lookup
# (place_name_nearest) and a name/kommun/län search (place_names_search),
# which callers can further narrow to one Locale's geometry themselves (see
# LocaleViewSet.place_names_search) since Lantmäteriet cannot clip for them.
ORTNAMN_NAMNTYPER: tuple[str, ...] = (
    "Anläggning",
    "Bebyggelse",
    "Tätort",
    "Glaciär",
    "Fornlämning",
    "Kyrka",
    "Naturvårdsområde",
    "Sankmark",
    "Natur- och terrängnamn",
    "Trakt",
    "Vattendelsområde",
    "Vattendrag",
    "Hav och sjö",
)


def _ortnamn_config() -> dict[str, Any]:
    return getattr(settings, "LANTMATERIET_ORTNAMN", {}) or {}


def _ortnamn_cache_key(params: dict[str, Any]) -> str:
    encoded = json.dumps(params, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"lantmateriet-ortnamn:{sha256(encoded).hexdigest()}"


def _sweref_point_to_wgs84_geojson(punkt: Any) -> dict[str, Any] | None:
    """Convert an Ortnamn Direkt ``punkt`` (SWEREF 99 TM GeoJSON Point,
    ``[easting, northing]``) to a WGS 84 GeoJSON Point ``[lon, lat]``."""
    if not isinstance(punkt, dict) or punkt.get("type") != "Point":
        return None
    coordinates = punkt.get("coordinates")
    if not isinstance(coordinates, (list, tuple)) or len(coordinates) < 2:
        return None
    lon, lat = geo.sweref99tm_to_wgs84(float(coordinates[0]), float(coordinates[1]))
    return {"type": "Point", "coordinates": [lon, lat]}


def place_names_search(
    *,
    namn: str | None = None,
    match: str | None = None,
    punkt: tuple[float, float] | None = None,
    lankod: str | None = None,
    kommunkod: str | None = None,
    namntyp: tuple[str, ...] | None = None,
    sprak: str | None = None,
    max_hits: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Search Ortnamn Direkt by name, point, county, or municipality.

    ``punkt`` is ``(longitude, latitude)`` in WGS 84. Ortnamn Direkt only
    speaks SWEREF 99, so it is converted to SWEREF 99 TM for the request
    (``punkt=northing,easting``, ``punktSrid=3006``) and every returned point
    is converted back to WGS 84 (see module notes above). When ``punkt`` is
    given, only the closest name is returned - there is no radius or bbox
    search - and ``max_hits``/``offset`` are not sent, because the API rejects
    them together with ``punkt``.

    Each returned feature is one (name, placement) pair: a name with several
    placements yields several features sharing the same ``id``.

    The upstream API requires at least one of ``namn`` or ``punkt``.
    """
    if not namn and not punkt:
        raise LantmaterietAPIError(
            "Either namn or punkt is required to search Ortnamn Direkt."
        )

    config = _ortnamn_config()
    base_url = str(config.get("BASE_URL", "")).rstrip("/")
    if not base_url:
        raise LantmaterietConfigurationError("Configure LANTMATERIET_ORTNAMN_BASE_URL.")

    params: dict[str, Any] = {"srid": 3006}
    if namn:
        params["namn"] = namn
    if match:
        params["match"] = match
    if punkt is not None:
        longitude, latitude = punkt
        easting, northing = geo.wgs84_to_sweref99tm(longitude, latitude)
        params["punkt"] = f"{northing:.1f},{easting:.1f}"
        params["punktSrid"] = 3006
    else:
        params["maxHits"] = max(1, min(max_hits, 400))
        params["offset"] = max(0, offset)
    if lankod:
        params["lankod"] = lankod
    if kommunkod:
        params["kommunkod"] = kommunkod
    if namntyp:
        params["namntyp"] = list(namntyp)
    if sprak:
        params["sprak"] = sprak

    cache_key = _ortnamn_cache_key(params)

    def _fetch() -> dict[str, Any]:
        import requests

        headers = {
            "Accept": "application/json",
            "Authorization": _authorization_header(config),
        }
        try:
            response = requests.get(
                f"{base_url}/kriterier",
                headers=headers,
                params=params,
                timeout=config.get("TIMEOUT", 15),
            )
        except requests.RequestException as exc:
            raise LantmaterietAPIError("Could not reach Lantmäteriet Ortnamn Direkt.") from exc
        _raise_for_status(response, "Ortnamn Direkt")
        try:
            payload = response.json()
        except ValueError as exc:
            raise LantmaterietAPIError(
                "Lantmäteriet Ortnamn Direkt returned invalid JSON."
            ) from exc

        features = []
        for item in payload.get("features") or []:
            properties = item.get("properties") if isinstance(item, dict) else None
            if not isinstance(properties, dict):
                continue
            for placement in properties.get("placering") or []:
                if not isinstance(placement, dict):
                    continue
                features.append(
                    {
                        "id": properties.get("id"),
                        "namn": properties.get("namn"),
                        "sprak": properties.get("sprak"),
                        "namntyp": placement.get("namntyp"),
                        "lankod": placement.get("lankod"),
                        "lannamn": placement.get("lannamn"),
                        "kommunkod": placement.get("kommunkod"),
                        "kommunnamn": placement.get("kommunnamn"),
                        "geometry": _sweref_point_to_wgs84_geojson(placement.get("punkt")),
                    }
                )
        return {"total": payload.get("totaltAntal", len(features)), "features": features}

    return _cache_singleflight(
        cache_key, config.get("CACHE_SECONDS", 60 * 60 * 24 * 30), _fetch
    )


def place_name_nearest(longitude: float, latitude: float) -> dict[str, Any] | None:
    """Return the closest Ortnamn Direkt placement to a WGS 84 point.

    The API answers with the nearest *name*, which may have several
    placements far apart (a name like "Stockholm" has three); the one closest
    to the query point is picked here rather than trusting response order.
    """
    result = place_names_search(punkt=(longitude, latitude))
    candidates = [f for f in result.get("features") or [] if f.get("geometry")]
    if not candidates:
        return None

    def _distance(feature: dict[str, Any]) -> float:
        lon, lat = feature["geometry"]["coordinates"]
        return geo.haversine_m(latitude, longitude, lat, lon)

    return min(candidates, key=_distance)


# --- Byggnad Direkt (buildings) ---------------------------------------------
#
# Another separate Lantmäteriet REST API (not OGC API Features), base path
# "distribution/produkter/byggnad/v3". Confirmed live (unauthenticated) that
# this base URL and its /health path are reachable: the gateway returns its
# own "Missing Credentials" error, not 404.
#
# Unlike Ortnamn Direkt, this product DOES accept an arbitrary search
# geometry: ``POST /referens/geometri`` takes a GeoJSON/GML polygon (plus an
# optional metre buffer) and returns buildings intersecting it - much closer
# to Marktäcke/Hydrografi's clip-to-geometry shape than Ortnamn's
# nearest-point-only search. The documented limits are a max polygon area of
# 1,000,000 m² and a max perimeter of 200,000 m per request, so a Locale (or
# its padded background-fetch area) larger than that is tiled into smaller
# geometries here rather than sent as one oversized request.
#
# NOT verified live: the response's building attribute field names
# (ändamål/purpose, name, floor count, area, ...) are undocumented in
# Geotorget's technical description, so building features are passed through
# unchanged rather than reshaped/renamed - the same "Lantmäteriet owns the
# attributes" principle as land_cover_map above, but here it is a necessity,
# not just a preference, since no field list exists to reshape against.
BYGGNAD_MAX_AREA_SQM_DEFAULT = 1_000_000
BYGGNAD_MAX_PERIMETER_M_DEFAULT = 200_000
BYGGNAD_MAX_TILES_DEFAULT = 400


def _byggnad_config() -> dict[str, Any]:
    return getattr(settings, "LANTMATERIET_BYGGNAD", {}) or {}


def _byggnad_cache_key(geometry: dict[str, Any]) -> str:
    encoded = json.dumps(geometry, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"lantmateriet-byggnad:{sha256(encoded).hexdigest()}"


def _bbox_tiles(
    bbox: tuple[float, float, float, float], max_side_metres: float
) -> list[tuple[float, float, float, float]]:
    """Split a WGS 84 bbox into a grid of sub-bboxes no wider than ``max_side_metres``.

    Uses the same equirectangular approximation as ``buffered_bbox`` above -
    accurate enough for sizing request tiles, not for precise area math.
    """
    import math

    min_lon, min_lat, max_lon, max_lat = bbox
    mid_lat = (min_lat + max_lat) / 2
    lat_m_per_deg = 111_320
    lon_m_per_deg = 111_320 * max(math.cos(math.radians(mid_lat)), 0.01)
    width_m = max((max_lon - min_lon) * lon_m_per_deg, 1.0)
    height_m = max((max_lat - min_lat) * lat_m_per_deg, 1.0)

    nx = max(1, math.ceil(width_m / max_side_metres))
    ny = max(1, math.ceil(height_m / max_side_metres))
    lon_step = (max_lon - min_lon) / nx
    lat_step = (max_lat - min_lat) / ny
    return [
        (
            min_lon + i * lon_step,
            min_lat + j * lat_step,
            min_lon + (i + 1) * lon_step,
            min_lat + (j + 1) * lat_step,
        )
        for i in range(nx)
        for j in range(ny)
    ]


def buildings_in_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
    """Return Byggnad Direkt building features clipped to a GeoJSON geometry.

    Tiles ``geometry`` into chunks respecting ``MAX_AREA_SQM``/
    ``MAX_PERIMETER_M`` (see module notes above), queries
    ``POST /referens/geometri`` per tile, and merges + dedups the results by
    building id. Each tile is itself cached via ``_cache_singleflight``, so
    re-fetching an unchanged area does not re-hit Lantmäteriet tile by tile.

    Raises ``LantmaterietMapTooLargeError`` if the geometry would need more
    than ``MAX_TILES`` requests - a safety limit, not a Lantmäteriet-imposed
    one, to stop an unreasonably large area from silently issuing hundreds of
    requests.
    """
    import math

    from shapely.geometry import box, mapping, shape

    try:
        target_shape = shape(geometry)
    except (TypeError, ValueError, KeyError) as exc:
        raise LantmaterietAPIError("Geometry is not valid GeoJSON.") from exc
    if target_shape.is_empty:
        return {"type": "FeatureCollection", "features": []}

    config = _byggnad_config()
    base_url = str(config.get("BASE_URL", "")).rstrip("/")
    if not base_url:
        raise LantmaterietConfigurationError("Configure LANTMATERIET_BYGGNAD_BASE_URL.")

    max_area = config.get("MAX_AREA_SQM", BYGGNAD_MAX_AREA_SQM_DEFAULT)
    max_perimeter = config.get("MAX_PERIMETER_M", BYGGNAD_MAX_PERIMETER_M_DEFAULT)
    # 0.9 safety margin: a square tile's own bbox area/perimeter should stay
    # comfortably under the documented limits even after this equirectangular
    # approximation's inevitable slack.
    max_side = min(math.sqrt(max_area), max_perimeter / 4) * 0.9

    tiles = _bbox_tiles(target_shape.bounds, max_side)
    max_tiles = config.get("MAX_TILES", BYGGNAD_MAX_TILES_DEFAULT)
    if len(tiles) > max_tiles:
        raise LantmaterietMapTooLargeError(
            "The requested area is too large for Byggnad Direkt; zoom in or choose a smaller area."
        )

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": _authorization_header(config),
    }

    def _fetch_tile(tile_geometry: dict[str, Any]) -> dict[str, Any]:
        import requests

        try:
            response = requests.post(
                f"{base_url}/referens/geometri",
                headers=headers,
                json={"Geometri": tile_geometry},
                timeout=config.get("TIMEOUT", 15),
            )
        except requests.RequestException as exc:
            raise LantmaterietAPIError("Could not reach Lantmäteriet Byggnad Direkt.") from exc
        _raise_for_status(response, "Byggnad Direkt")
        try:
            return response.json()
        except ValueError as exc:
            raise LantmaterietAPIError(
                "Lantmäteriet Byggnad Direkt returned invalid JSON."
            ) from exc

    features: dict[Any, dict[str, Any]] = {}
    for tile_bbox in tiles:
        tile_shape = box(*tile_bbox).intersection(target_shape)
        if tile_shape.is_empty:
            continue
        tile_geometry = mapping(tile_shape)
        cache_key = _byggnad_cache_key(tile_geometry)
        payload = _cache_singleflight(
            cache_key,
            config.get("CACHE_SECONDS", 60 * 60 * 24 * 30),
            lambda tile_geometry=tile_geometry: _fetch_tile(tile_geometry),
        )
        for item in payload.get("features") or []:
            if not isinstance(item, dict):
                continue
            building_id = item.get("id") or (item.get("properties") or {}).get("id")
            features.setdefault(building_id, item)

    return {"type": "FeatureCollection", "features": list(features.values())}
