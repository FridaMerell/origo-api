"""Recommend rest stops along a planned route where the wildlife is worth a
stop - ranked by species *variety and rarity*, never by raw report volume.

Given a route ``LineString`` and a corridor width this module:

1. walks the route at a regular stride (:func:`tempus.services.geo.densify`);
2. scores each sample point from a ``TaxonAggregation`` in its circle
   (:mod:`tempus.services.diversity`), reading each taxon's *rarity* from a
   precomputed ``significance`` (0..1) rather than a live corridor baseline;
3. for the best sections, pulls recent records with a ``Search``, clusters them
   by Artportalen *site* and returns the best-scoring **named** site - so a stop
   is "Nyanlagda dammen, Stenkvistafältet", never "Eskilstuna";
4. de-duplicates and returns the top ``num_stops`` as plain dicts, each spelling
   out *which taxa* make the stop worthwhile.

The per-taxon ``significance`` comes from ``significance_of`` - a
``taxon_id -> float | None`` callable. Left unset, a Django-backed lookup reads
``Phenogram.significance`` (for the province the route runs through) then
``Species.significance``; tests inject a plain dict. The scoring maths stays
pure and network/Django settings live in :mod:`tempus.services.artdatabanken`.
Each API response is cached (``django.core.cache``) for a few hours because one
call fans out into dozens of near-identical requests. Runs in
``tempus.tasks.compute_route_suggestions``, not a request.
"""

import datetime
import hashlib
import json
import logging
import re

from django.core.cache import cache

from tempus.services import artdatabanken, diversity, geo

logger = logging.getLogger(__name__)

# How many sample points to split a route into, at most; the stride is the
# larger of the corridor width and route_length / this.
_MAX_SAMPLES = 40
_COARSE_KEEP_FACTOR = 2      # keep 2x num_stops after the coarse pass
_SEARCH_TAKE = 500          # records pulled per winner to cluster into sites
# Route geometry does not include an estimated driving time. Treat 150 km as
# the practical equivalent of a 2.5-hour trip when deciding whether a detour
# stop near either endpoint is useful.
_SHORT_TRIP_NO_EDGE_BUFFER_M = 150_000
# A candidate site needs at least this many distinct taxa reported recently -
# below it the "locality" is usually a garden feeder or a street address.
_MIN_SITE_TAXA = 6

# Observation fields the site search needs (the API omits locality/locationId
# from the default response).
_SEARCH_FIELDS = [
    "taxon.id", "taxon.scientificName", "taxon.vernacularName",
    "event.startDate",
    "location.locality", "location.locationId",
    "location.decimalLatitude", "location.decimalLongitude",
    "location.municipality", "location.county",
]

# Observation data barely moves within a planning session, and a single route
# suggestion fans out into dozens of near-identical API calls (one per sample
# point, plus a grid + search per winner). Cache each response so re-running a
# route - or two routes that share a corridor - stays cheap.
_API_CACHE_TTL = 6 * 60 * 60


def _cache_key(kind: str, *parts) -> str:
    blob = json.dumps(parts, sort_keys=True, default=str)
    digest = hashlib.sha1(blob.encode("utf-8")).hexdigest()
    return f"tempus:route_planner:{kind}:{digest}"


def _cached(kind: str, key_parts, producer):
    key = _cache_key(kind, *key_parts)
    hit = cache.get(key)
    if hit is not None:
        return hit
    value = producer()
    cache.set(key, value, _API_CACHE_TTL)
    return value


def _taxon_aggregation(flt: dict, *, take: int) -> dict:
    return _cached("taxon_agg", (flt, take),
                   lambda: artdatabanken.taxon_aggregation(flt, take=take))


def _search_observations(flt: dict, **kwargs) -> dict:
    return _cached("search", (flt, kwargs),
                   lambda: artdatabanken.search_observations(flt, **kwargs))


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


def _taxon_rows(agg: dict, significance_of=None, *,
                today: datetime.date | None = None) -> list[diversity.TaxonRow]:
    """Rows from a ``TaxonAggregation`` response.

    The live SOS shape is a flat ``{"taxonId", "observationCount", "firstSighting",
    "lastSighting"}`` per record - no nested taxon block and no names (those are
    filled later from a Dyntaxa batch / the recent-records search). Older/other
    shapes with a nested ``taxon`` are still tolerated.
    """
    rows: list[diversity.TaxonRow] = []
    for rec in (agg or {}).get("records", []) or []:
        taxon = rec.get("taxon") or {}
        tid = rec.get("taxonId") or taxon.get("id") or taxon.get("taxonId")
        if tid is None:
            continue
        tid = int(tid)
        last_seen = None
        if today is not None:
            last_seen = _age_days(rec.get("lastSighting") or "", today)
        rows.append(diversity.TaxonRow(
            taxon_id=tid,
            count=int(rec.get("observationCount") or rec.get("count") or 0),
            scientific_name=taxon.get("scientificName", ""),
            vernacular_name=taxon.get("vernacularName", "") or taxon.get("swedishName", ""),
            red_list_category=(taxon.get("redListCategory")
                               or _first(taxon.get("redListCategories"))
                               or ""),
            last_seen_days=last_seen,
            significance=significance_of(tid) if significance_of else None,
        ))
    return rows


def _first(value):
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value


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
    edge_buffer_m: float | None = None,
    min_gap_m: float | None = None,
    today: datetime.date | None = None,
    significance_of=None,
) -> list[dict]:
    """Ranked rest-stop suggestions for a route.

    ``geometry`` is a GeoJSON ``LineString`` dict (``Route.geometry``);
    ``corridor_metres`` is ``Route.corridor_metres``. ``significance_of`` maps a
    Dyntaxa taxon id to its rarity (0..1) or ``None``; left unset it is built
    from the database.

    ``edge_buffer_m`` drops stops within that distance of either end of the route
    (you don't want a "rest stop" where you started or are about to arrive);
    ``min_gap_m`` is the minimum along-route spacing between kept stops. Both
    default to sensible fractions of the route length. Returns a list of dicts
    ordered best-first - see the module docstring for the shape.
    """
    today = today or datetime.date.today()
    coords = [tuple(c) for c in geometry["coordinates"]]
    if len(coords) < 2:
        raise ValueError("route geometry needs at least two coordinates")

    if significance_of is None:
        significance_of = _default_significance_lookup(coords)

    total_m = geo.line_length_m(coords)
    stride = max(corridor_metres, total_m / _MAX_SAMPLES)
    samples = geo.densify(coords, stride)
    date = _date_filter(since_days, today=today)

    if edge_buffer_m is None:
        # On a short trip, a good site close to the start or destination can
        # still be worth a deliberate detour. Longer trips retain a small
        # endpoint buffer so suggested rest stops do not duplicate the ends.
        edge_buffer_m = (
            0.0 if total_m < _SHORT_TRIP_NO_EDGE_BUFFER_M
            else max(corridor_metres, 0.025 * total_m)
        )
    edge_buffer_m = min(edge_buffer_m, 0.4 * total_m)  # never exclude the whole route
    if min_gap_m is None:
        min_gap_m = max(corridor_metres, 0.5 * total_m / max(num_stops, 1))

    # Coarse pass: score every sample point. A single failing aggregation is
    # logged and skipped rather than aborting the whole run.
    scored: list[dict] = []
    api_errors = 0
    for lon, lat in samples:
        flt = {**_base_filter(taxon_id, date),
               "geographics": _point_geographics(lon, lat, corridor_metres)}
        try:
            agg = _taxon_aggregation(flt, take=1000)
        except artdatabanken.ArtdatabankenAPIError as exc:
            api_errors += 1
            logger.warning("route sample %.4f,%.4f aggregation failed: %s", lon, lat, exc)
            continue
        rows = _taxon_rows(agg, significance_of, today=today)
        if not rows:
            continue
        result = diversity.score(rows)
        along = geo.distance_along_line(coords, (lon, lat))
        # Do this before the coarse ranking. Otherwise endpoint candidates can
        # occupy every winner slot, only to be discarded after localisation,
        # leaving no interior sites to consider.
        if along < edge_buffer_m or along > total_m - edge_buffer_m:
            continue
        scored.append({"lon": lon, "lat": lat, "result": result, "rows": rows})

    if not scored:
        logger.info(
            "suggest_rest_stops: %d sample(s), no scored points (%d API error(s))",
            len(samples), api_errors,
        )
        return []

    mean_corrected = sum(s["result"].breakdown["corrected_richness"]
                         for s in scored) / len(scored)
    for s in scored:
        s["result"] = diversity.score(s["rows"], reference_richness=mean_corrected)

    scored.sort(key=lambda s: s["result"].score, reverse=True)
    winners = scored[: max(num_stops * _COARSE_KEEP_FACTOR, num_stops)]

    # Names + red-list for every taxon across the winners, one Dyntaxa batch.
    enrich = _enrich_taxa({r.taxon_id for s in winners for r in s["rows"]})

    # Fine pass: localise each winner and read its recent records.
    suggestions: list[dict] = []
    for s in winners:
        try:
            spot = _localise(s, coords, corridor_metres, taxon_id, date,
                             notable_days, today, enrich)
        except artdatabanken.ArtdatabankenAPIError as exc:
            api_errors += 1
            logger.warning("localise %.4f,%.4f failed: %s", s["lon"], s["lat"], exc)
            continue
        if spot is None:
            continue  # no named site in this section worth a stop
        # distance along route / detour
        pt = spot["location"]["coordinates"]
        _, detour = geo.nearest_point_on_line(coords, pt)
        along = geo.distance_along_line(coords, pt)
        spot["detour_m"] = round(detour, 1)
        spot["distance_along_route_m"] = round(along, 1)
        if max_detour_m is not None and detour > max_detour_m:
            continue
        if along < edge_buffer_m or along > total_m - edge_buffer_m:
            continue  # too close to where the trip starts / ends
        suggestions.append(spot)

    # De-duplicate: keep the best-scoring stop, then only stops at least
    # ``min_gap_m`` further along the route than every stop already kept.
    suggestions.sort(key=lambda x: x["score"], reverse=True)
    kept: list[dict] = []
    for spot in suggestions:
        along = spot["distance_along_route_m"]
        if any(abs(along - k["distance_along_route_m"]) < min_gap_m for k in kept):
            continue
        kept.append(spot)
        if len(kept) >= num_stops:
            break

    for rank, spot in enumerate(kept, start=1):
        spot["rank"] = rank
    logger.info(
        "suggest_rest_stops: %d sample(s), %d scored, %d winner(s), "
        "%d kept, %d API error(s)",
        len(samples), len(scored), len(winners), len(kept), api_errors,
    )
    return kept


def _default_significance_lookup(coords):
    """A ``taxon_id -> float | None`` lookup backed by the database.

    Reads ``Phenogram.significance`` for the province the route midpoint falls
    in, then ``Species.significance``. Returns a lookup that always yields
    ``None`` if the ORM or the reference data is unavailable (tests inject their
    own lookup and never reach this).
    """
    try:
        from tempus.models import GeoArea, Phenogram, Species
    except Exception:  # pragma: no cover - ORM not configured
        return lambda taxon_id: None

    try:
        species_sig = dict(
            Species.objects.filter(significance__isnull=False)
            .values_list("dyntaxa_taxon_id", "significance")
        )
        mid = geo.point_at_distance(coords, geo.line_length_m(coords) / 2)
        province = next(
            (a for a in GeoArea.objects.filter(kind=GeoArea.Kind.PROVINCE)
             if geo.point_in_multipolygon(mid, a.geometry)),
            None,
        )
        area_sig: dict[int, tuple[int, float]] = {}
        if province is not None:
            rows = (
                Phenogram.objects
                .filter(geo_area=province, significance__isnull=False)
                .values_list("species__dyntaxa_taxon_id", "years", "significance")
            )
            for tid, years, sig in rows:
                if tid is None:
                    continue
                prev = area_sig.get(tid)
                if prev is None or years > prev[0]:
                    area_sig[tid] = (years, sig)
    except Exception:  # pragma: no cover - defensive
        logger.exception("significance lookup could not be built")
        return lambda taxon_id: None

    def lookup(taxon_id: int):
        hit = area_sig.get(taxon_id)
        if hit is not None:
            return hit[1]
        return species_sig.get(taxon_id)

    return lookup


def _name_of(value) -> str:
    """SOS ``location.county`` / ``.municipality`` are ``{featureId, name}``
    dicts in the live API but plain strings in older payloads."""
    if isinstance(value, dict):
        return value.get("name") or ""
    return value or ""


_REDLIST_CODE = re.compile(r"\(([A-Za-z]{2})\)\s*$")
_REDLIST_CODES = {"NT", "VU", "EN", "CR", "RE", "DD"}


def _redlist_code(value) -> str:
    """Dyntaxa returns the red-list status as a Swedish phrase - ``"Sårbar (VU)"``,
    ``"Nationellt utdöd (RE)"``. Pull the bare IUCN code, or ``""``."""
    if not isinstance(value, str) or not value.strip():
        return ""
    m = _REDLIST_CODE.search(value.strip())
    code = (m.group(1) if m else value.strip()).upper()
    return code if code in _REDLIST_CODES else ""


def _enrich_taxa(taxon_ids) -> dict[int, tuple[str, str, str]]:
    """``{taxon_id: (scientific_name, vernacular_name, red_list_category)}`` from
    one Dyntaxa batch - ``TaxonAggregation`` carries none of these."""
    ids = sorted({int(t) for t in taxon_ids if int(t) > 0})
    if not ids:
        return {}
    try:
        taxa = artdatabanken.get_taxa(ids)
    except artdatabanken.ArtdatabankenAPIError as exc:
        logger.warning("taxon enrichment failed: %s", exc)
        return {}
    out: dict[int, tuple[str, str, str]] = {}
    for td in taxa:
        raw = td.get("api_data") or {}
        out[td["dyntaxa_taxon_id"]] = (
            td.get("scientific_name", "") or "",
            td.get("swedish_name", "") or "",
            _redlist_code(raw.get("redlistCategory") or raw.get("redListCategory")),
        )
    return out


_SITE_SUFFIX = re.compile(r",\s*[A-Za-zÅÄÖåäö]{1,4}\.?\s*$")


def _clean_site_name(name: str) -> str:
    """Trim the region abbreviation Artportalen appends (``"..., Srm"``)."""
    name = (name or "").strip()
    return _SITE_SUFFIX.sub("", name).strip(" ,") or name


def _site_rows(records, enrich, today) -> list[diversity.TaxonRow]:
    """One :class:`~tempus.services.diversity.TaxonRow` per taxon across a
    locality's recent records (raw record counts, per the design)."""
    agg: dict[int, dict] = {}
    for rec in records:
        tid = _dotted(rec, "taxon.id")
        if tid is None:
            continue
        tid = int(tid)
        age = _age_days(_dotted(rec, "event.startDate"), today)
        e = agg.setdefault(tid, {
            "count": 0, "age": None,
            "sci": _dotted(rec, "taxon.scientificName", ""),
            "vern": _dotted(rec, "taxon.vernacularName", ""),
        })
        e["count"] += 1
        if age is not None and (e["age"] is None or age < e["age"]):
            e["age"] = age
    rows: list[diversity.TaxonRow] = []
    for tid, e in agg.items():
        sci, vern, cat = enrich.get(tid, ("", "", ""))
        rows.append(diversity.TaxonRow(
            taxon_id=tid, count=e["count"],
            scientific_name=e["sci"] or sci,
            vernacular_name=e["vern"] or vern,
            red_list_category=cat,
            last_seen_days=e["age"],
        ))
    return rows


def _localise(sample, coords, corridor_metres, taxon_id, date, notable_days,
              today, enrich=None):
    """Resolve a winning route section to the single best *named* site in it.

    Pulls the section's recent records (with locality fields the default
    response omits), clusters them by Artportalen site, scores each site's
    species mix and returns the best one that has a real name and enough
    variety. ``None`` when there is no named site worth a stop.
    """
    enrich = enrich or {}
    lon, lat = sample["lon"], sample["lat"]

    flt = {**_base_filter(taxon_id, date),
           "geographics": _point_geographics(lon, lat, corridor_metres),
           "output": {"fields": _SEARCH_FIELDS}}
    page = _search_observations(flt, take=_SEARCH_TAKE,
                                sort_by="event.startDate", sort_order="Desc")
    records = (page or {}).get("records", []) or []

    groups: dict[str, dict] = {}
    for rec in records:
        loc = rec.get("location") or {}
        name = (loc.get("locality") or "").strip()
        key = loc.get("locationId") or name
        if not key or not name:
            continue  # unnamed / imprecise record - cannot be a "stop"
        g = groups.setdefault(key, {
            "name": name, "location_id": loc.get("locationId") or "",
            "county": _name_of(loc.get("county")),
            "municipality": _name_of(loc.get("municipality")),
            "lls": [], "records": [],
        })
        g["records"].append(rec)
        plat, plon = loc.get("decimalLatitude"), loc.get("decimalLongitude")
        if plat is not None and plon is not None:
            g["lls"].append((float(plat), float(plon)))

    scored_sites = []
    for g in groups.values():
        rows = _site_rows(g["records"], enrich, today)
        if len([r for r in rows if r.count > 0]) < _MIN_SITE_TAXA:
            continue
        scored_sites.append((diversity.score(rows), g, rows))
    if not scored_sites:
        return None

    result, g, rows = max(scored_sites, key=lambda t: t[0].score)
    lls = g["lls"] or [(lat, lon)]
    site_lat = sum(p[0] for p in lls) / len(lls)
    site_lon = sum(p[1] for p in lls) / len(lls)

    notable_recent = sorted((
        {"taxon_id": r.taxon_id, "scientific_name": r.scientific_name,
         "vernacular_name": r.vernacular_name, "last_seen_days": r.last_seen_days,
         "red_list_category": r.red_list_category}
        for r in rows
        if r.effective_significance >= diversity.NOTABLE_SIGNIFICANCE
        and r.last_seen_days is not None and r.last_seen_days <= notable_days
    ), key=lambda x: x["last_seen_days"])

    highlights = [{
        "taxon_id": c.taxon_id, "scientific_name": c.scientific_name,
        "vernacular_name": c.vernacular_name, "count": c.count,
        "last_seen_days": c.last_seen_days, "red_list_category": c.red_list_category,
        "reason": c.reason,
    } for c in result.contributions[:8]]

    top_species = sorted(
        ({"scientific_name": r.scientific_name, "vernacular_name": r.vernacular_name,
          "count": r.count} for r in rows if r.count > 0),
        key=lambda x: x["count"], reverse=True,
    )[:15]

    return {
        "score": result.score,
        "breakdown": result.breakdown,
        "location": geo.as_geojson_point((site_lon, site_lat)),
        "locality": _clean_site_name(g["name"]),
        "location_id": g["location_id"],
        "municipality": g["municipality"],
        "county": g["county"],
        "species_count": result.richness,
        "highlights": highlights,
        "notable_recent": notable_recent[:10],
        "top_species": top_species,
    }
