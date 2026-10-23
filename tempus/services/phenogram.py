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

# Grid zoom for the occupied-cell counts behind Phenogram.significance. Coarse
# enough that a twitched rarity mobbed at one spot fills one cell, not many.
SIGNIFICANCE_GRID_ZOOM = 10
# The area-wide "all taxa" occupied-cell count is the same for every species in
# an area, so cache it across a fan-out.
SIGNIFICANCE_AREA_CACHE_TTL = 24 * 60 * 60


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


def _occupied_cells(grid) -> int:
    """Number of grid cells with at least one observation, tolerant of the
    ``gridCells`` / ``records`` key difference between API versions."""
    cells = (grid or {}).get("gridCells") or (grid or {}).get("records") or []
    return sum(
        1 for c in cells
        if int(c.get("observationsCount") or c.get("count") or 0) > 0
    )


def _significance(species, geo_area, curve):
    """``(value, basis)`` - rarity of a *report* of this species in this area,
    from the occupied-cell share against all reporting effort there.

    Two ``GeoGridAggregation`` calls: one filtered to the species, one (cached
    per area+window) for all taxa. ``geo_area=None`` measures against the whole
    country.
    """
    date = {
        "startDate": curve["date_from"],
        "endDate": curve["date_to"],
        "dateFilterType": "BetweenStartDateAndEndDate",
    }
    base = {"date": date, "occurrenceStatus": "Present"}
    if geo_area is not None and geo_area.geometry:
        base["geographics"] = {"geometries": [geo_area.geometry]}

    from django.conf import settings
    grid_timeout = float(
        (getattr(settings, "ARTDATABANKEN", {}) or {}).get(
            "PHENOGRAM_TIMEOUT", 60
        )
    )

    area_key = "tempus:sig_area:{}:{}:{}:{}".format(
        geo_area.pk if geo_area is not None else "range",
        curve["date_from"], curve["date_to"], SIGNIFICANCE_GRID_ZOOM,
    )
    area_cells = cache.get(area_key)
    if area_cells is None:
        area_cells = _occupied_cells(artdatabanken.geo_grid_aggregation(
            base, zoom=SIGNIFICANCE_GRID_ZOOM, timeout=grid_timeout))
        cache.set(area_key, area_cells, SIGNIFICANCE_AREA_CACHE_TTL)

    species_flt = {
        **base,
        "taxon": {"ids": [species.dyntaxa_taxon_id], "includeUnderlyingTaxa": True},
    }
    species_cells = _occupied_cells(artdatabanken.geo_grid_aggregation(
        species_flt, zoom=SIGNIFICANCE_GRID_ZOOM, timeout=grid_timeout))

    value = diversity.significance_from_cells(species_cells, area_cells)
    basis = {
        "species_cells": species_cells,
        "area_cells": area_cells,
        "share": round(species_cells / area_cells, 6) if area_cells else None,
        "zoom": SIGNIFICANCE_GRID_ZOOM,
    }
    return value, basis


# Species.significance is a species' rarity among its relatives, so that a
# group few people report (moths) is not mistaken for a rare one. It is
# measured within these Dyntaxa ranks (taxon category ids), narrowest first:
# family, order, class. Never above class: that would be all reporting again.
REFERENCE_RANKS = (11, 8, 5)
# A reference group with fewer occupied cells than this is too thin to measure
# against, and the next rank up is used instead.
REFERENCE_MIN_CELLS = 200
# Nor does a group say anything when the species itself fills most of it (a
# family with one Swedish species): above this share the next rank up is used.
REFERENCE_MAX_SHARE = 0.75
# Parents and ranks hardly ever change in Dyntaxa.
LINEAGE_CACHE_TTL = 30 * 24 * 60 * 60
# The value counts occupied cell+month pairs over this many whole months, so a
# species found everywhere but seldom (capercaillie) is not taken for common.
SEASON_MONTHS = 24
# The group is counted only in the species' own months, so a migrant is not
# made rare by the winter it spends abroad. A month is the species' own when it
# fills at least this share of its busiest month's cells; a stray winter record
# does not open the whole winter.
SEASON_SHARE = 0.10
# A past month's cell count does not change, so a group's is kept this long.
SEASON_CACHE_TTL = 30 * 24 * 60 * 60


def _grid_timeout() -> float:
    from django.conf import settings

    return float((getattr(settings, "ARTDATABANKEN", {}) or {}).get("PHENOGRAM_TIMEOUT", 60))


def _parent_and_rank(taxon_id: int) -> tuple[int | None, int | None]:
    """A Dyntaxa taxon's parent id and rank id, cached across species."""
    key = f"tempus:dyntaxa_lineage:{taxon_id}"
    hit = cache.get(key)
    if hit is None:
        taxon = artdatabanken.get_taxon(taxon_id)
        category = (taxon.get("api_data") or {}).get("category") or {}
        hit = [taxon.get("parent_dyntaxa_taxon_id"), category.get("id") if isinstance(category, dict) else None]
        cache.set(key, hit, LINEAGE_CACHE_TTL)
    parent, rank = hit
    return (int(parent) if parent else None), (int(rank) if rank is not None else None)


def reference_groups(species) -> list[int]:
    """The species' family, order and class as Dyntaxa taxon ids, narrowest
    first; a rank missing from its lineage is skipped. Stops at class."""
    parent = species.parent_dyntaxa_taxon_id or _parent_and_rank(species.dyntaxa_taxon_id)[0]
    groups: list[int] = []
    seen = {species.dyntaxa_taxon_id}
    while parent and parent not in seen:
        seen.add(parent)
        grandparent, rank = _parent_and_rank(parent)
        if rank in REFERENCE_RANKS:
            groups.append(parent)
            if rank == REFERENCE_RANKS[-1]:
                break
        parent = grandparent
    return groups


def _taxon_cells(taxon_id: int, date: dict) -> int:
    """Occupied grid cells in the whole country for a taxon and its underlying taxa."""
    flt = {
        "date": date,
        "occurrenceStatus": "Present",
        "taxon": {"ids": [int(taxon_id)], "includeUnderlyingTaxa": True},
    }
    return _occupied_cells(
        artdatabanken.geo_grid_aggregation(flt, zoom=SIGNIFICANCE_GRID_ZOOM, timeout=_grid_timeout())
    )


def _season_months(today: datetime.date) -> list[dict]:
    """Date filters for the last :data:`SEASON_MONTHS` whole months, oldest first."""
    months = []
    end = today.replace(day=1)
    for _ in range(SEASON_MONTHS):
        start = (end - datetime.timedelta(days=1)).replace(day=1)
        months.append({
            "startDate": start.isoformat(),
            "endDate": (end - datetime.timedelta(days=1)).isoformat(),
            "dateFilterType": "BetweenStartDateAndEndDate",
        })
        end = start
    return months[::-1]


def _cached_cells(key: str, taxon_id: int, date: dict, timeout: int) -> int:
    cells = cache.get(key)
    if cells is None:
        cells = _taxon_cells(taxon_id, date)
        cache.set(key, cells, timeout)
    return cells


def _reference_group(species, groups: list[int], date: dict) -> int | None:
    """The narrowest group wide enough to measure against: at least
    :data:`REFERENCE_MIN_CELLS` cells, with the species in at most
    :data:`REFERENCE_MAX_SHARE` of them. A species too common for every group
    is measured against the widest one that is not too thin."""
    species_cells = _taxon_cells(species.dyntaxa_taxon_id, date)
    widest = None
    for group in groups:
        key = f"tempus:sig_group:{group}:{date['startDate']}:{date['endDate']}:{SIGNIFICANCE_GRID_ZOOM}"
        group_cells = _cached_cells(key, group, date, SIGNIFICANCE_AREA_CACHE_TTL)
        if group_cells < REFERENCE_MIN_CELLS:
            continue
        if species_cells <= group_cells * REFERENCE_MAX_SHARE:
            return group
        widest = group
    return widest


def refresh_species_significance(species, *, years: int = DEFAULT_YEARS, today: datetime.date | None = None):
    """Compute and store ``Species.significance`` - how rare a report of this
    species is among reports of its relatives - without building a phenogram.

    The reference group is the species' family (or order, or class, when the
    narrower group is too thin or mostly the species itself; see
    :data:`REFERENCE_RANKS` and :func:`_reference_group`), chosen on occupied
    cells over the last ``years`` calendar years. The value then sets the
    species' occupied cell+month pairs over the last :data:`SEASON_MONTHS`
    whole months against the group's in the same months, counting only the
    months the species is about (:data:`SEASON_SHARE`). That is one grid call
    per month for the species; the group's are cached across its species.
    Red-list status is not folded in; readers add it
    (``diversity.RED_LIST_BUMP``). Returns the value, or ``None`` when no group
    is wide enough to measure against; the stored value is then left as it was.
    """
    from tempus.models import Species

    years = max(1, min(int(years), MAX_YEARS))
    today = today or datetime.date.today()
    groups = reference_groups(species)
    if not groups:
        return None
    group = _reference_group(species, groups, _date_filter(years, today=today))
    if group is None:
        return None

    months = _season_months(today)
    own = [_taxon_cells(species.dyntaxa_taxon_id, month) for month in months]
    # With no record at all every month counts, and the species reads as rare.
    floor = max(own) * SEASON_SHARE
    season = [i for i, cells in enumerate(own) if cells >= floor]
    group_cells = sum(
        _cached_cells(
            f"tempus:sig_month:{group}:{months[i]['startDate']}:{SIGNIFICANCE_GRID_ZOOM}",
            group, months[i], SEASON_CACHE_TTL,
        )
        for i in season
    )
    value = diversity.significance_from_cells(sum(own[i] for i in season), group_cells)
    if value is None:
        return None
    Species.objects.filter(pk=species.pk).update(significance=value)
    return value


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
    """
    from tempus.models import Phenogram

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
        value, basis = _significance(species, geo_area, curve)
        defaults["significance"] = value
        defaults["significance_basis"] = basis
    except (
        artdatabanken.ArtdatabankenConfigurationError,
        artdatabanken.ArtdatabankenAPIError,
    ) as exc:
        logger.warning(
            "significance for %s / %s skipped: %s", species, geo_area or "range", exc
        )

    # Species.significance is measured against the species' relatives by
    # refresh_species_significance, so this whole-range value is not copied there.
    row, _ = Phenogram.objects.update_or_create(
        species=species,
        geo_area=geo_area,
        years=years,
        defaults=defaults,
    )
    return row
