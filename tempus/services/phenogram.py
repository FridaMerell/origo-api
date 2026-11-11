"""Turn Species Observation System records into a seasonal activity curve.

A thin orchestration layer between :mod:`tempus.services.artdatabanken` (network
+ Django settings) and :mod:`tempus.services.phenology` (pure maths, tested
there).

- :func:`build_phenogram` is model-free like :mod:`tempus.services.route_planner`
  - it fetches, declusters and shapes the curve, and returns a plain dict.
- :func:`get_phenogram` is the persistence layer: it returns the stored
  :class:`tempus.models.Phenogram` row and only calls :func:`build_phenogram`
  when the row is missing or ``refresh=True``. Rendering code calls this and
  never rebuilds per request.

Seasonal status ("in season", "going out of season", ...) is derived from a
stored row's day-of-year envelope by :mod:`tempus.services.season`; nothing is
distilled into a separate table.

The SOS ``geographics`` / ``taxon`` / ``date`` filter keys mirror
``tempus.services.route_planner``; confirm them against the SOS OpenAPI document
on the developer portal.
"""

import datetime
import logging

from django.core.cache import cache
from django.utils import timezone

from tempus.services import artdatabanken, diversity, phenology

logger = logging.getLogger(__name__)

DEFAULT_YEARS = 8
MAX_YEARS = 30
DEFAULT_SMOOTH_WEEKS = 1

# Cap the observation crawl. Declustering already removes mob bias, so a sample
# is enough for a phenogram; this keeps a common species to ~4 SOS pages.
DEFAULT_MAX_RECORDS = 4000

# Grid zoom for the grid cells behind Phenogram.significance: fine enough to
# tell a province's cells apart. SOS refuses a query with more than 65,535
# possible cells (a large province or the whole country at 12), and then the
# next coarser zoom is tried, down to SIGNIFICANCE_MIN_ZOOM.
SIGNIFICANCE_GRID_ZOOM = 12
SIGNIFICANCE_MIN_ZOOM = 9
# Significance pools cell+year pairs over this many whole calendar years.
SIGNIFICANCE_YEARS = 3
# A whole year's counts hardly change, so a group's are shared by all its
# species for this long, and so are the report counts behind relevance and a
# species' Swedish presence from Artfakta.
SIGNIFICANCE_CACHE_TTL = 30 * 24 * 60 * 60
# Artfakta speciesdata/taxonomy: a species whose swedishPresence starts with
# this and whose immigrationHistory is not SPONTANEOUS (released, escaped or
# spread from introduced populations, never established) gets no significance.
# Vagrants that arrived on their own and established introduced species keep it.
CASUAL_PRESENCE_PREFIX = "Tillfällig"
SPONTANEOUS = "Spontan"
# Sweden's bounding box, the whole-country significance area.
SWEDEN_EXTENT = {
    "type": "Polygon",
    "coordinates": [[[10.5, 55.2], [24.2, 55.2], [24.2, 69.1], [10.5, 69.1], [10.5, 55.2]]],
}


def _date_filter(years: int, *, today: datetime.date) -> dict:
    start = datetime.date(today.year - years + 1, 1, 1)
    return {
        "startDate": start.isoformat(),
        "endDate": today.isoformat(),
        "dateFilterType": "BetweenStartDateAndEndDate",
    }


def _search_filter(taxon_id: int, geometry: dict | None, date: dict) -> dict:
    flt: dict = {
        "date": date,
        "occurrenceStatus": "Present",
        "taxon": {"ids": [int(taxon_id)], "includeUnderlyingTaxa": True},
    }
    if geometry:
        flt["geographics"] = {"geometries": [geometry]}
    return flt


def build_phenogram(
    *,
    taxon_id: int,
    geometry: dict | None = None,
    years: int = DEFAULT_YEARS,
    smooth_weeks: int = DEFAULT_SMOOTH_WEEKS,
    decluster: bool = True,
    max_records: int = DEFAULT_MAX_RECORDS,
    today: datetime.date | None = None,
) -> dict:
    """Weekly activity curve for a taxon over the last ``years`` calendar years.

    Pure compute: fetches up to ``max_records`` SOS observations, optionally
    declusters twitching mobs, and shapes a 52-week curve. ``geometry`` is an
    optional GeoJSON geometry (e.g. ``GeoArea.geometry``) to clip the search to.
    Returns a JSON-ready dict; :func:`get_phenogram` persists it. Expensive -
    never call this from a render path.
    """
    if taxon_id is None or int(taxon_id) <= 0:
        raise ValueError("taxon_id must be a positive integer")
    years = max(1, min(int(years), MAX_YEARS))
    smooth_weeks = max(0, int(smooth_weeks))
    max_records = max(0, int(max_records))
    today = today or datetime.date.today()

    date = _date_filter(years, today=today)
    search_filter = _search_filter(taxon_id, geometry, date)

    records = []
    for record in artdatabanken.iter_observations(search_filter):
        records.append(record)
        if max_records and len(records) >= max_records:
            break
    if decluster:
        dates = list(phenology.decluster(records))
    else:
        dates = phenology.observation_dates(records)

    raw = phenology.phenogram(dates)
    smoothed = phenology.smooth(raw, smooth_weeks) if smooth_weeks else raw
    fraction = phenology.normalize(smoothed)
    lo_week, hi_week = phenology.activity_window(smoothed)
    years_present = len({day.year for day in dates})
    truncated = bool(max_records and len(records) >= max_records)

    return {
        "taxon_id": int(taxon_id),
        "years": years,
        "date_from": date["startDate"],
        "date_to": date["endDate"],
        "smooth_weeks": smooth_weeks,
        "declustered": bool(decluster),
        "record_count": len(records),
        "record_limit_hit": truncated,
        "sample_count": len(dates),
        "years_present": years_present,
        "peak_week": phenology.peak_week(smoothed),
        "activity_window": {"start_week": lo_week, "end_week": hi_week},
        "season_window_days": phenology.season_window_days(
            smoothed, years_present=years_present
        ),
        "weeks": [
            {
                "week": week,
                "count": raw[week],
                "smoothed": smoothed[week],
                "fraction": fraction[week],
            }
            for week in phenology.WEEKS
        ],
    }


def _row_defaults(curve: dict) -> dict:
    window = curve["season_window_days"]
    return {
        "date_from": datetime.date.fromisoformat(curve["date_from"]),
        "date_to": datetime.date.fromisoformat(curve["date_to"]),
        "weeks": curve["weeks"],
        "peak_week": curve["peak_week"],
        "window_start_week": curve["activity_window"]["start_week"],
        "window_end_week": curve["activity_window"]["end_week"],
        "start_day_of_year": window["start_day_of_year"],
        "peak_start_day": window["peak_start_day"],
        "peak_end_day": window["peak_end_day"],
        "end_day_of_year": window["end_day_of_year"],
        "confidence": window["confidence"],
        "smooth_weeks": curve["smooth_weeks"],
        "declustered": curve["declustered"],
        "record_count": curve["record_count"],
        "record_limit_hit": curve["record_limit_hit"],
        "sample_count": curve["sample_count"],
        "years_present": curve["years_present"],
        "computed_at": timezone.now(),
    }


def _taxa_per_cell(grid) -> dict[str, int]:
    """Taxa reported per occupied grid cell, keyed by the cell's tile
    position, tolerant of the ``gridCells`` / ``records`` key difference
    between API versions."""
    cells = (grid or {}).get("gridCells") or (grid or {}).get("records") or []
    counts = {}
    for c in cells:
        if int(c.get("observationsCount") or c.get("count") or 0) > 0:
            key = f"{c['x']}:{c['y']}" if "x" in c and "y" in c else repr(c.get("boundingBox"))
            counts[key] = int(c.get("taxaCount") or 0)
    return counts


def _grid_timeout() -> float:
    from django.conf import settings

    return float((getattr(settings, "ARTDATABANKEN", {}) or {}).get("PHENOGRAM_TIMEOUT", 60))


def _year_filter(taxon_id: int, year: int, geo_area=None) -> dict:
    flt = {
        "date": {
            "startDate": f"{year}-01-01",
            "endDate": f"{year}-12-31",
            "dateFilterType": "BetweenStartDateAndEndDate",
        },
        "occurrenceStatus": "Present",
        "taxon": {"ids": [int(taxon_id)], "includeUnderlyingTaxa": True},
    }
    # Without an area, Sweden's extent: unclipped, the grid spans every stray
    # coordinate in SOS and passes its 65,535-cell limit.
    geometry = geo_area.geometry if geo_area is not None and geo_area.geometry else SWEDEN_EXTENT
    flt["geographics"] = {"geometries": [geometry]}
    return flt


def _cells(taxon_id: int, year: int, geo_area, zoom: int) -> dict[str, int]:
    """Taxa per occupied grid cell for a taxon and its underlying taxa in one
    year."""
    return _taxa_per_cell(artdatabanken.geo_grid_aggregation(
        _year_filter(taxon_id, year, geo_area), zoom=zoom, timeout=_grid_timeout()))


def _too_many_cells(exc: artdatabanken.ArtdatabankenAPIError) -> bool:
    return exc.status == 400 and "too large" in (exc.body or "")


def _group_cells(group: int, year: int, geo_area=None) -> tuple[int, dict[str, int]]:
    """``(zoom, cells)``: :func:`_cells` for a species group at the finest zoom
    SOS accepts for the area, shared by all its species, which are counted at
    the same zoom."""
    key = "tempus:sig_group_taxa_cells:{}:{}:{}:{}".format(
        group, geo_area.pk if geo_area is not None else "range", year, SIGNIFICANCE_GRID_ZOOM,
    )
    found = cache.get(key)
    if found is None:
        zoom = SIGNIFICANCE_GRID_ZOOM
        while True:
            try:
                found = (zoom, _cells(group, year, geo_area, zoom))
                break
            except artdatabanken.ArtdatabankenAPIError as exc:
                if zoom <= SIGNIFICANCE_MIN_ZOOM or not _too_many_cells(exc):
                    raise
                zoom -= 1
        cache.set(key, found, SIGNIFICANCE_CACHE_TTL)
    return found


def _report_count(group: int, years: list[int]) -> int:
    """Reports of a species group in the whole country over ``years``."""
    key = f"tempus:group_reports:{group}:{years[0]}:{years[-1]}"
    count = cache.get(key)
    if count is None:
        flt = _year_filter(group, years[0])
        flt["date"]["endDate"] = f"{years[-1]}-12-31"
        count = artdatabanken.count_observations(flt, timeout=_grid_timeout())
        cache.set(key, count, SIGNIFICANCE_CACHE_TTL)
    return count


def _swedish_presence(taxon_id: int) -> dict:
    """``{"swedishPresence", "immigrationHistory"}`` from Artfakta
    ``speciesdata/taxonomy`` for one taxon, cached; empty when Artfakta has
    no entry for it."""
    key = f"tempus:swedish_presence:{taxon_id}"
    found = cache.get(key)
    if found is None:
        rows = artdatabanken._species_dataset(int(taxon_id), "taxonomy") or []
        data = (rows[0].get("speciesData") if rows and isinstance(rows[0], dict) else None) or {}
        found = {
            "swedishPresence": data.get("swedishPresence") or "",
            "immigrationHistory": data.get("immigrationHistory") or "",
        }
        cache.set(key, found, SIGNIFICANCE_CACHE_TTL)
    return found


def _without_swedish_occurrence(presence: dict) -> bool:
    """Casual in Sweden and not arrived on its own (see
    :data:`CASUAL_PRESENCE_PREFIX`)."""
    return (
        presence.get("swedishPresence", "").startswith(CASUAL_PRESENCE_PREFIX)
        and bool(presence.get("immigrationHistory"))
        and presence.get("immigrationHistory") != SPONTANEOUS
    )


def primary_group(species) -> int | None:
    """Dyntaxa taxon id of the species' primary Tempus species group: the
    primary category (``is_primary``) it is a member of, directly or below in
    the category tree. With several, the lowest taxon id, so the choice is
    stable. ``None`` when it has none, or that category has no taxon id."""
    from tempus.models import SpeciesCategory

    categories = {
        category.pk: category
        for category in SpeciesCategory.objects.only("pk", "parent_category", "is_primary", "taxon_id")
    }
    found = set()
    for pk in species.category_memberships.values_list("category_id", flat=True):
        seen = set()
        while pk is not None and pk not in seen and pk in categories:
            seen.add(pk)
            category = categories[pk]
            if category.is_primary:
                if category.taxon_id:
                    found.add(category.taxon_id)
                break
            pk = category.parent_category_id
    return min(found) if found else None


def _relevance(group: int, years: list[int]) -> float | None:
    """How much a species group is reported, against the most reported
    primary group (see :func:`diversity.relevance_from_counts`)."""
    from tempus.models import SpeciesCategory

    groups = set(
        SpeciesCategory.objects.filter(is_primary=True, taxon_id__isnull=False)
        .values_list("taxon_id", flat=True)
    ) | {group}
    top = max(_report_count(taxon_id, years) for taxon_id in groups)
    return diversity.relevance_from_counts(_report_count(group, years), top)


def _significance(species, geo_area, *, today: datetime.date):
    """``(value, basis)`` - how much a *report* of this species in this area
    stands out: its rarity within its primary Tempus species group there,
    times the group's relevance.

    Rarity is the species' spread over every grid cell+year pair the group
    was reported in during the last :data:`SIGNIFICANCE_YEARS` whole years, in
    this area (``geo_area=None`` is the whole country), each pair weighted by
    the number of the group's taxa reported in it - how well it is surveyed
    for the group: Σ weight of the pairs the species is in ÷ Σ weight of all
    (see :func:`diversity.significance_from_spread`). Reports are not counted,
    so an inventory or a twitched bird cannot raise a species' spread, and a
    cell where an inventory reported only its target species weighs almost
    nothing. Seasons do not enter, only cells.

    The cells are as fine as SOS allows for the area
    (:data:`SIGNIFICANCE_GRID_ZOOM`, coarser for a large one). One grid call
    per year for the species; the group's calls, the report counts behind
    relevance and the species' Swedish presence are cached.
    ``(None, {})`` when the species has no primary group, ``(None, basis)``
    when it has no Swedish occurrence (:func:`_without_swedish_occurrence`)
    or the group has no records in the area.
    """
    group = primary_group(species)
    if group is None:
        return None, {}
    presence = _swedish_presence(species.dyntaxa_taxon_id)
    if _without_swedish_occurrence(presence):
        return None, {
            "swedish_presence": presence["swedishPresence"],
            "immigration_history": presence["immigrationHistory"],
        }
    years = list(range(today.year - SIGNIFICANCE_YEARS, today.year))
    group_years = {year: _group_cells(group, year, geo_area) for year in years}
    group_cells = sum(len(cells) for _, cells in group_years.values())
    basis = {
        "group": group,
        "years": years,
        "group_cells": group_cells,
        "zoom": [zoom for zoom, _ in group_years.values()],
    }
    if not group_cells:
        return None, basis
    total_weight = sum(sum(taxa.values()) for _, taxa in group_years.values())
    if not total_weight:
        return None, basis
    species_cells = 0
    species_weight = 0
    for year, (zoom, group_taxa) in group_years.items():
        cells = _cells(species.dyntaxa_taxon_id, year, geo_area, zoom)
        species_cells += len(cells)
        species_weight += sum(group_taxa.get(key, 0) for key in cells)
    spread = species_weight / total_weight if total_weight else 0.0
    rarity = diversity.significance_from_spread(spread, group_cells)
    relevance = _relevance(group, years)
    basis.update(
        species_cells=species_cells,
        spread=round(spread, 6),
        rarity=rarity,
        relevance=relevance,
    )
    if rarity is None or relevance is None:
        return None, basis
    return round(rarity * relevance, 3), basis


def get_phenogram(
    species,
    geo_area=None,
    *,
    years: int = DEFAULT_YEARS,
    refresh: bool = False,
    create: bool = True,
    today: datetime.date | None = None,
):
    """Return the stored :class:`tempus.models.Phenogram` for this species/area.

    Builds and saves one only when it is missing or ``refresh=True``, and only
    if ``create`` is set - the crawl is expensive, so render paths pass
    ``create=False`` and enqueue :func:`tempus.tasks.generate_phenogram`
    instead, getting ``None`` until the worker has run. Never triggered by a
    plain read.

    A build also measures the significance of a report of the species in the
    area (:func:`_significance`); the whole-range build stores it on the
    species too. When the measurement fails, the stored values are kept.
    """
    from tempus.models import Phenogram, Species

    years = max(1, min(int(years), MAX_YEARS))
    existing = Phenogram.objects.filter(
        species=species, geo_area=geo_area, years=years
    ).first()
    if existing is not None and not refresh:
        return existing
    if not create:
        return existing

    curve = build_phenogram(
        taxon_id=species.dyntaxa_taxon_id,
        geometry=(geo_area.geometry or None) if geo_area is not None else None,
        years=years,
        today=today,
    )
    defaults = _row_defaults(curve)
    try:
        value, basis = _significance(species, geo_area, today=today or datetime.date.today())
        defaults["significance"] = value
        defaults["significance_basis"] = basis
    except (
        artdatabanken.ArtdatabankenConfigurationError,
        artdatabanken.ArtdatabankenAPIError,
    ) as exc:
        logger.warning(
            "significance for %s / %s skipped: %s", species, geo_area or "range", exc
        )

    row, _ = Phenogram.objects.update_or_create(
        species=species,
        geo_area=geo_area,
        years=years,
        defaults=defaults,
    )
    if geo_area is None and "significance" in defaults:
        Species.objects.filter(pk=species.pk).update(significance=defaults["significance"])
    return row
