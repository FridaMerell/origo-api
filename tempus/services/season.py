"""Seasonal status for a species, read straight from its stored ``Phenogram``.

No network and no rebuild: this reads the day-of-year envelope already on the
:class:`tempus.models.Phenogram` row (computed by
:mod:`tempus.services.phenogram`) and reports where today sits in it. Safe to
call on every render and to map over a queryset.
"""

import datetime

from tempus.services import phenology

# Re-exported so callers have one import for the vocabulary.
STATUSES = phenology.SEASON_STATUSES

# Which ``phenogram_status`` key each queryable status name reads. The five
# ``status`` values are exact matches; the rest are the overlapping booleans
# ("in season" stays true through peak and the last-chance tail).
_BOOL_KEYS = {
    "in_season": "is_in_season",
    "coming_into_season": "is_coming_into_season",
    "going_out_of_season": "is_going_out_of_season",
    "at_peak": "at_peak",
}


def status_for(phenogram, *, today=None) -> dict:
    """Where ``today`` sits in this ``Phenogram`` row's activity curve."""
    today = today or datetime.date.today()
    return phenology.phenogram_status(
        {
            "start_day_of_year": phenogram.start_day_of_year,
            "peak_start_day": phenogram.peak_start_day,
            "peak_end_day": phenogram.peak_end_day,
            "end_day_of_year": phenogram.end_day_of_year,
        },
        today.timetuple().tm_yday,
    )


def matches_status(phenogram, wanted: str, *, today=None) -> bool:
    """True if ``phenogram``'s current status satisfies ``wanted``.

    ``wanted`` is one of :data:`STATUSES` (exact ``status`` match) or one of
    ``in_season`` / ``coming_into_season`` / ``going_out_of_season`` /
    ``at_peak`` / ``out_of_season`` (the overlapping view, e.g. ``in_season``
    stays true at peak and through the last-chance tail).
    """
    result = status_for(phenogram, today=today)
    if wanted in _BOOL_KEYS:
        return bool(result[_BOOL_KEYS[wanted]])
    if wanted == "out_of_season":
        return result["status"] == "out_of_season"
    return result["status"] == wanted


def valid_status(wanted: str) -> bool:
    return wanted in STATUSES or wanted in _BOOL_KEYS or wanted == "out_of_season"


def filter_by_status(queryset, wanted: str, *, today=None) -> list:
    """The rows of ``queryset`` (Phenograms) whose current status matches.

    Evaluated in Python - the window can wrap the year, so this is not a plain
    ``WHERE``.
    """
    return [pg for pg in queryset if matches_status(pg, wanted, today=today)]
