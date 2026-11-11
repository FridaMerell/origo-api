"""Client for the IAU Meteor Data Center's list of established meteor showers.

The MDC publishes the list as a pipe-separated text file whose name carries the
year of the latest revision (``streamestablisheddata2026.txt``), linked from
https://www.ta3.sk/IAUC22DB/MDC2022/Roje/roje_lista.php. The link is read from
that page so that a new revision is picked up without a code change.

Verified live: each data line is a row of double-quoted fields separated by
``|``; one shower has several rows, one per published solution. The columns
used here are, by position: 3 code, 6 name, 8 LoSb, 9 LoSe, 10 LoS (solar
longitudes of the start, end and maximum of activity), 11 Ra, 12 De (radiant at
the maximum, J2000), 13 dRa, 14 dDe (radiant drift per degree of solar
longitude), 15 Vg (geocentric speed, km/s) and 28 N (number of meteors behind
the solution). Empty fields are blank.

The MDC has no rates and its activity periods are long video tails, so which
showers are returned, their visual activity period, maximum, radiant at the
maximum, speed and zenithal hourly rate all come from the IMO's working list
(:mod:`caelus.services.imo`), read anew each year. The MDC adds what the IMO
list lacks: the radiant drift, from the solution with the most meteors.
"""

import logging
import re
from typing import Any

from django.core.cache import cache

from caelus.services import imo

logger = logging.getLogger(__name__)

LIST_URL = "https://www.ta3.sk/IAUC22DB/MDC2022/Roje/roje_lista.php"
FILE_BASE_URL = "https://www.ta3.sk/IAUC22DB/MDC2022/Etc/"
# The list is revised a few times a year.
CACHE_SECONDS = 60 * 60 * 24
TIMEOUT_SECONDS = 30

_CACHE_KEY = "caelus-iau-mdc-showers:4"
_FILE_PATTERN = re.compile(r"streamestablisheddata\d{4}\.txt")


class IauMdcAPIError(RuntimeError):
    """Raised when the IAU MDC cannot serve a valid shower list."""


def _number(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def _rows(text: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        if not line.startswith('"'):
            continue
        fields = [field.strip().strip('"').strip() for field in line.split("|")]
        if len(fields) > 28:
            rows.append(fields)
    return rows


def _best(solutions: list[list[str]], *columns: int) -> list[str] | None:
    """The solution with the most meteors that has all the given columns."""
    complete = [row for row in solutions if all(_number(row[column]) is not None for column in columns)]
    return max(complete, key=lambda row: _number(row[28]) or 0, default=None)


def parse_showers(text: str, working_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return one entry per shower in the IMO working list, with the MDC's drift.

    ``text`` is the MDC list's text, or empty when the MDC could not be read;
    the radiant then stays where it is at the maximum.
    """
    by_code: dict[str, list[list[str]]] = {}
    for row in _rows(text):
        by_code.setdefault(row[3], []).append(row)

    showers = []
    for shower in working_list:
        solutions = by_code.get(shower["code"], [])
        drift = _best(solutions, 13, 14)
        named = _best(solutions)
        showers.append(
            {
                **shower,
                # The MDC's plain name, e.g. "eta Aquariids" rather than the IMO's "η-Aquariids".
                "name": named[6] if named else shower["name"],
                "ra_drift": _number(drift[13]) if drift else 0.0,
                "dec_drift": _number(drift[14]) if drift else 0.0,
            }
        )
    return showers


def get_showers() -> list[dict[str, Any]]:
    """Return the notable annual meteor showers with radiant, activity and ZHR.

    ``peak``, ``start`` and ``end`` are solar longitudes (degrees, J2000). The
    drifts are degrees per degree of solar longitude. Raises
    :class:`IauMdcAPIError` when the IMO working list cannot be had; without
    the MDC the showers come without drift.
    """
    cached = cache.get(_CACHE_KEY)
    if cached is not None:
        return cached

    try:
        working_list = imo.get_working_list()
    except imo.ImoAPIError as exc:
        raise IauMdcAPIError(str(exc)) from exc

    try:
        text = _read_established()
    except IauMdcAPIError as exc:
        logger.warning("iau_mdc: showers without radiant drift: %s", exc)
        showers = parse_showers("", working_list)
        # Try the MDC again soon instead of keeping the showers without drift for a day.
        cache.set(_CACHE_KEY, showers, timeout=60 * 15)
        return showers

    showers = parse_showers(text, working_list)
    cache.set(_CACHE_KEY, showers, timeout=CACHE_SECONDS)
    return showers


def _read_established() -> str:
    """The text of the MDC's latest list of established showers."""
    import requests

    try:
        page = requests.get(LIST_URL, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise IauMdcAPIError("Could not reach the IAU MDC.") from exc
    if not page.ok:
        raise IauMdcAPIError(f"The IAU MDC returned HTTP {page.status_code}.")
    match = _FILE_PATTERN.search(page.text)
    if not match:
        raise IauMdcAPIError("The IAU MDC page has no link to the established showers.")

    try:
        response = requests.get(FILE_BASE_URL + match.group(0), timeout=TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise IauMdcAPIError("Could not reach the IAU MDC.") from exc
    if not response.ok:
        raise IauMdcAPIError(f"The IAU MDC returned HTTP {response.status_code}.")
    return response.text
