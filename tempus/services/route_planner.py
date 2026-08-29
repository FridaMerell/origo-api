"""Recommend rest stops along a planned route where the wildlife is worth a
stop - ranked by species *variety and rarity*, never by raw report volume.

Given a route ``LineString`` and a corridor width this module:

1. walks the route at a regular stride (:func:`tempus.services.geo.densify`);
2. pulls one corridor-wide taxon breakdown for a rarity baseline;
3. scores each sample point from a ``TaxonAggregation`` in its circle
   (:mod:`tempus.services.diversity`);
4. localises the best points to a specific spot with a fine
   ``GeoGridAggregation`` + a recent-records ``Search``;
5. de-duplicates and returns the top ``num_stops`` as plain dicts, each spelling
   out *which taxa* make the stop worthwhile.

Network + Django settings live in :mod:`tempus.services.artdatabanken`; the
maths is pure and tested separately. This function is deliberately free of
Django models so it can be exercised from a shell or a test with a fake
session; a ``Route``-aware wrapper can wrap it when the endpoint is built.
"""

import datetime

from tempus.services import artdatabanken, diversity, geo

# How many sample points to split a route into, at most; the stride is the
# larger of the corridor width and route_length / this.
_MAX_SAMPLES = 40
_COARSE_KEEP_FACTOR = 2      # keep 2x num_stops after the coarse pass
_FINE_GRID_ZOOM = 14         # ~hundreds of metres per cell
_SEARCH_TAKE = 50


def _dotted(record, path, default=None):
    node = record
    for part in path.split("."):
        node = node.get(part) if isinstance(node, dict) else None
        if node is None:
            return default
    return node


def _date_filter(since_days: int, *, today: datetime.date) -> dict:
    start = today - datetime.timedelta(days=since_days)
    return {
        "startDate": start.isoformat(),
        "endDate": today.isoformat(),
        "dateFilterType": "BetweenStartDateAndEndDate",
    }


def _base_filter(taxon_id: int | None, date: dict) -> dict:
    flt: dict = {"date": date, "occurrenceStatus": "Present"}
    if taxon_id:
        flt["taxon"] = {"ids": [int(taxon_id)], "includeUnderlyingTaxa": True}
    return flt


def _point_geographics(lon: float, lat: float, radius_m: float) -> dict:
    return {
        "geometries": [{"type": "Point", "coordinates": [lon, lat]}],
        "maxDistanceFromPoint": int(radius_m),
    }


def _taxon_rows(agg: dict) -> list[diversity.TaxonRow]:
    rows: list[diversity.TaxonRow] = []
    for rec in (agg or {}).get("records", []) or []:
        taxon = rec.get("taxon") or {}
        tid = taxon.get("id") or taxon.get("taxonId")
        if tid is None:
            continue
        rows.append(diversity.TaxonRow(
            taxon_id=int(tid),
            count=int(rec.get("count") or rec.get("observationCount") or 0),
            scientific_name=taxon.get("scientificName", ""),
            vernacular_name=taxon.get("vernacularName", "") or taxon.get("swedishName", ""),
            red_list_category=(taxon.get("redListCategory")
                               or _first(taxon.get("redListCategories"))
                               or ""),
        ))
    return rows


def _first(value):
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value


def _grid_cells(grid: dict) -> list[tuple[float, float, int]]:
    """Return ``[(lon, lat, count)]`` centroids, tolerant of API-version keys."""
    cells = (grid or {}).get("gridCells") or (grid or {}).get("records") or []
    out: list[tuple[float, float, int]] = []
    for cell in cells:
        count = int(cell.get("observationsCount") or cell.get("count") or 0)
        box = cell.get("boundingBox") or cell.get("bbox") or cell.get("geometry")
        centroid = _box_centroid(box)
        if centroid:
            out.append((centroid[0], centroid[1], count))
    return out


def _box_centroid(box):
    if box is None:
        return None
    if isinstance(box, (list, tuple)) and len(box) == 4:
        return geo.bbox_centroid(box)
    if isinstance(box, dict):
        tl = box.get("topLeft") or box.get("northWest")
        br = box.get("bottomRight") or box.get("southEast")
        if tl and br:
            lons = [tl.get("longitude", tl.get("lon")), br.get("longitude", br.get("lon"))]
            lats = [tl.get("latitude", tl.get("lat")), br.get("latitude", br.get("lat"))]
            if None not in lons and None not in lats:
                return ((lons[0] + lons[1]) / 2.0, (lats[0] + lats[1]) / 2.0)
        coords = box.get("coordinates")
        if coords:  # a GeoJSON polygon ring
            ring = coords[0] if coords and isinstance(coords[0][0], (list, tuple)) else coords
            lons = [p[0] for p in ring]
            lats = [p[1] for p in ring]
            return (sum(lons) / len(lons), sum(lats) / len(lats))
    return None


def _age_days(iso_date: str, today: datetime.date) -> float | None:
    if not iso_date:
        return None
    try:
        d = datetime.date.fromisoformat(str(iso_date)[:10])
    except ValueError:
        return None
    return max(0.0, (today - d).days)


def suggest_rest_stops(
    geometry: dict,
    corridor_metres: int,
    *,
    taxon_id: int | None = None,
    since_days: int = 30,
    notable_days: int = 10,
    max_detour_m: float | None = None,
    num_stops: int = 5,
    today: datetime.date | None = None,
) -> list[dict]:
    """Ranked rest-stop suggestions for a route.

    ``geometry`` is a GeoJSON ``LineString`` dict (``Route.geometry``);
    ``corridor_metres`` is ``Route.corridor_metres``. Returns a list of dicts
    ordered best-first - see the module docstring for the shape.
    """
    today = today or datetime.date.today()
    coords = [tuple(c) for c in geometry["coordinates"]]
    if len(coords) < 2:
        raise ValueError("route geometry needs at least two coordinates")

    total_m = geo.line_length_m(coords)
    stride = max(corridor_metres, total_m / _MAX_SAMPLES)
    samples = geo.densify(coords, stride)
    cumulative = geo.cumulative_distances(coords)
    date = _date_filter(since_days, today=today)

    # 1. Corridor-wide baseline for the rarity term.
    corridor_flt = {**_base_filter(taxon_id, date), "geographics": {
        "geometries": [{"type": "Point", "coordinates": [lon, lat]} for lon, lat in samples],
        "maxDistanceFromPoint": int(corridor_metres),
    }}
    corridor_agg = artdatabanken.taxon_aggregation(corridor_flt, take=1000)
    corridor_rows = _taxon_rows(corridor_agg)
    corridor_freq = diversity.corridor_frequencies(
        {r.taxon_id: r.count for r in corridor_rows}
    )

    # 2. Coarse pass: score every sample point.
    scored: list[dict] = []
    for lon, lat in samples:
        flt = {**_base_filter(taxon_id, date),
               "geographics": _point_geographics(lon, lat, corridor_metres)}
        rows = _taxon_rows(artdatabanken.taxon_aggregation(flt, take=1000))
        if not rows:
            continue
        result = diversity.score(rows, corridor_freq)
        scored.append({"lon": lon, "lat": lat, "result": result, "rows": rows})

    if not scored:
        return []

    mean_corrected = sum(s["result"].breakdown["corrected_richness"]
                         for s in scored) / len(scored)
    for s in scored:
        s["result"] = diversity.score(s["rows"], corridor_freq,
                                      reference_richness=mean_corrected)

    scored.sort(key=lambda s: s["result"].score, reverse=True)
    winners = scored[: max(num_stops * _COARSE_KEEP_FACTOR, num_stops)]

    # 3. Fine pass: localise each winner and read its recent records.
    suggestions: list[dict] = []
    for s in winners:
        spot = _localise(s, coords, corridor_metres, taxon_id, date,
                         notable_days, today, corridor_freq)
        # distance along route / detour
        snapped, detour = geo.nearest_point_on_line(coords, spot["location"]["coordinates"])
        spot["detour_m"] = round(detour, 1)
        spot["distance_along_route_m"] = round(_distance_along(coords, cumulative, snapped), 1)
        if max_detour_m is not None and detour > max_detour_m:
            continue
        suggestions.append(spot)

    # 4. De-duplicate: drop a suggestion too close to a better-ranked one.
    suggestions.sort(key=lambda x: x["score"], reverse=True)
    kept: list[dict] = []
    for spot in suggestions:
        lon, lat = spot["location"]["coordinates"]
        if any(geo.haversine_m(lat, lon, k["location"]["coordinates"][1],
                               k["location"]["coordinates"][0]) < stride
               for k in kept):
            continue
        kept.append(spot)
        if len(kept) >= num_stops:
            break

    for rank, spot in enumerate(kept, start=1):
        spot["rank"] = rank
    return kept


def _localise(sample, coords, corridor_metres, taxon_id, date, notable_days,
              today, corridor_freq):
    lon, lat = sample["lon"], sample["lat"]

    grid = artdatabanken.geo_grid_aggregation(
        {**_base_filter(taxon_id, date),
         "geographics": _point_geographics(lon, lat, corridor_metres)},
        zoom=_FINE_GRID_ZOOM,
    )
    cells = _grid_cells(grid)
    if cells:
        best = max(cells, key=lambda c: c[2])
        spot_lon, spot_lat = best[0], best[1]
    else:
        spot_lon, spot_lat = lon, lat
    spot_lon, spot_lat = geo.snap_towards(
        (spot_lon, spot_lat), coords, max_offset_m=corridor_metres
    )

    # Recent records in the cell - for locality name + real last-seen dates.
    search_flt = {**_base_filter(taxon_id, date), "geographics": _point_geographics(
        spot_lon, spot_lat, max(corridor_metres / 2, 500))}
    page = artdatabanken.search_observations(
        search_flt, take=_SEARCH_TAKE,
        sort_by="event.startDate", sort_order="Desc",
    )
    records = (page or {}).get("records", []) or []

    last_seen: dict[int, float] = {}
    locality = county = ""
    notable_recent: list[dict] = []
    for rec in records:
        tid = _dotted(rec, "taxon.id")
        age = _age_days(_dotted(rec, "event.startDate"), today)
        if tid is not None and age is not None:
            last_seen.setdefault(int(tid), age)
        if not locality:
            locality = _dotted(rec, "location.locality", "") or _dotted(rec, "location.municipality", "")
            county = _dotted(rec, "location.county", "")

    # Re-score with real record ages attached.
    by_id = {r.taxon_id: r for r in sample["rows"]}
    for tid, age in last_seen.items():
        if tid in by_id:
            by_id[tid].last_seen_days = age
    rescored = diversity.score(list(by_id.values()), corridor_freq)

    for rec in records:
        cat = _first(_dotted(rec, "taxon.redListCategory")) or _dotted(rec, "taxon.redListCategory", "")
        age = _age_days(_dotted(rec, "event.startDate"), today)
        if age is not None and age <= notable_days and (cat or ""):
            notable_recent.append({
                "scientific_name": _dotted(rec, "taxon.scientificName", ""),
                "vernacular_name": _dotted(rec, "taxon.vernacularName", ""),
                "date": _dotted(rec, "event.startDate", "")[:10],
                "locality": _dotted(rec, "location.locality", ""),
                "red_list_category": cat,
            })

    highlights = [{
        "taxon_id": c.taxon_id,
        "scientific_name": c.scientific_name,
        "vernacular_name": c.vernacular_name,
        "count": c.count,
        "last_seen_days": c.last_seen_days,
        "red_list_category": c.red_list_category,
        "reason": c.reason,
    } for c in rescored.contributions[:8]]

    top_species = sorted(
        ({"scientific_name": r.scientific_name, "vernacular_name": r.vernacular_name,
          "count": r.count} for r in sample["rows"] if r.count > 0),
        key=lambda x: x["count"], reverse=True,
    )[:15]

    return {
        "score": rescored.score,
        "breakdown": rescored.breakdown,
        "location": geo.as_geojson_point((spot_lon, spot_lat)),
        "locality": locality,
        "county": county,
        "species_count": rescored.richness,
        "highlights": highlights,
        "notable_recent": notable_recent[:10],
        "top_species": top_species,
    }


def _distance_along(coords, cumulative, snapped) -> float:
    """Approximate distance from the route start to the projection of ``snapped``."""
    slon, slat = snapped
    best_d, best_along = float("inf"), 0.0
    for i, (a, b) in enumerate(zip(coords, coords[1:])):
        mid_lon = (a[0] + b[0]) / 2
        mid_lat = (a[1] + b[1]) / 2
        d = geo.haversine_m(slat, slon, mid_lat, mid_lon)
        if d < best_d:
            best_d = d
            best_along = (cumulative[i] + cumulative[i + 1]) / 2
    return best_along
