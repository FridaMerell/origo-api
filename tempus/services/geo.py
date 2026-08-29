"""Small, dependency-free geometry helpers for working with GeoJSON stored in
``JSONField``s (see ``tempus/README.md`` "Geographic data storage").

Pure functions, no Django and no network - cheap to test and reuse from
management commands, the API layer or :mod:`tempus.services.route_planner`.
Coordinates follow the GeoJSON convention: ``[longitude, latitude]`` in WGS 84
decimal degrees.

There is no GIS runtime in this project, so distances use a spherical-earth
haversine and along-route interpolation uses a local equirectangular
approximation. Both are well within tolerance for the corridor widths
(hundreds of metres to a few kilometres) this module is used with.
"""

import math

EARTH_RADIUS_M = 6_371_000.0

Coord = tuple[float, float]  # (lon, lat)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _coord(point) -> Coord:
    """Accept a ``(lon, lat)`` pair or a GeoJSON ``Point`` dict."""
    if isinstance(point, dict):
        point = point["coordinates"]
    lon, lat = point[0], point[1]
    return float(lon), float(lat)


def segment_lengths(coords) -> list[float]:
    """Metre length of each consecutive segment of a line (``len(coords) - 1``)."""
    out: list[float] = []
    for (lon1, lat1), (lon2, lat2) in zip(coords, coords[1:]):
        out.append(haversine_m(lat1, lon1, lat2, lon2))
    return out


def cumulative_distances(coords) -> list[float]:
    """Distance from the first vertex to each vertex, in metres (starts at 0)."""
    out = [0.0]
    for length in segment_lengths(coords):
        out.append(out[-1] + length)
    return out


def line_length_m(coords) -> float:
    return sum(segment_lengths(coords))


def point_at_distance(coords, distance_m: float) -> Coord:
    """Interpolate the ``(lon, lat)`` a given distance along the line.

    Clamped to the endpoints. Interpolation is linear in lon/lat, which is
    accurate enough over a single route segment at Swedish latitudes.
    """
    if distance_m <= 0:
        return _coord(coords[0])
    cumulative = cumulative_distances(coords)
    total = cumulative[-1]
    if distance_m >= total:
        return _coord(coords[-1])
    for i, (start, end) in enumerate(zip(cumulative, cumulative[1:])):
        if distance_m <= end:
            span = end - start or 1.0
            t = (distance_m - start) / span
            (lon1, lat1), (lon2, lat2) = coords[i], coords[i + 1]
            return (lon1 + (lon2 - lon1) * t, lat1 + (lat2 - lat1) * t)
    return _coord(coords[-1])


def densify(coords, spacing_m: float) -> list[Coord]:
    """Sample points evenly along a polyline, ``spacing_m`` metres apart.

    The first and last vertices are always included. Used to walk a route
    corridor at a regular stride.
    """
    if spacing_m <= 0:
        raise ValueError("spacing_m must be positive")
    coords = [_coord(c) for c in coords]
    if len(coords) < 2:
        return list(coords)
    total = line_length_m(coords)
    steps = max(1, math.ceil(total / spacing_m))
    points = [point_at_distance(coords, i * total / steps) for i in range(steps + 1)]
    return points


def bbox_centroid(bbox) -> Coord:
    """Centre of a ``[min_lon, min_lat, max_lon, max_lat]`` bounding box."""
    min_lon, min_lat, max_lon, max_lat = bbox
    return ((min_lon + max_lon) / 2.0, (min_lat + max_lat) / 2.0)


def nearest_point_on_line(coords, point) -> tuple[Coord, float]:
    """Closest point on the polyline to ``point`` and its distance in metres.

    Projection is done in a local equirectangular frame (metres) centred on the
    query point, so it is accurate for the short offsets involved in snapping a
    hotspot back toward a road.
    """
    plon, plat = _coord(point)
    lat0 = math.radians(plat)
    mx = math.cos(lat0) * EARTH_RADIUS_M * math.pi / 180.0  # metres per deg lon
    my = EARTH_RADIUS_M * math.pi / 180.0                   # metres per deg lat

    def to_xy(c: Coord) -> tuple[float, float]:
        return ((c[0] - plon) * mx, (c[1] - plat) * my)

    coords = [_coord(c) for c in coords]
    best_xy, best_d2 = (0.0, 0.0), math.inf
    for a, b in zip(coords, coords[1:]):
        ax, ay = to_xy(a)
        bx, by = to_xy(b)
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        t = 0.0 if seg2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / seg2))
        cx, cy = ax + dx * t, ay + dy * t
        d2 = cx * cx + cy * cy
        if d2 < best_d2:
            best_d2, best_xy = d2, (cx, cy)
    snapped = (plon + best_xy[0] / mx, plat + best_xy[1] / my)
    return snapped, math.sqrt(best_d2)


def snap_towards(point, coords, max_offset_m: float | None = None) -> Coord:
    """Move ``point`` partway toward the line so the suggested coordinate sits
    near the road rather than deep in a marsh.

    If ``max_offset_m`` is given and the point is already within it, the point
    is returned unchanged; otherwise it is pulled onto the line.
    """
    snapped, distance = nearest_point_on_line(coords, point)
    if max_offset_m is not None and distance <= max_offset_m:
        return _coord(point)
    return snapped


def as_geojson_point(coord: Coord) -> dict:
    lon, lat = coord
    return {"type": "Point", "coordinates": [lon, lat]}
