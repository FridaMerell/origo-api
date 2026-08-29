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

from django.utils import timezone

from tempus.services import artdatabanken, phenology

DEFAULT_YEARS = 8
MAX_YEARS = 30
DEFAULT_SMOOTH_WEEKS = 1

# Cap the observation crawl. Declustering already removes mob bias, so a sample
# is enough for a phenogram; this keeps a common species to ~4 SOS pages.
DEFAULT_MAX_RECORDS = 4000


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
    row, _ = Phenogram.objects.update_or_create(
        species=species,
        geo_area=geo_area,
        years=years,
        defaults=_row_defaults(curve),
    )
    return row
