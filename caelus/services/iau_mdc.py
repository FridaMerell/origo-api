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

For each shower the solution with the most meteors is used; its maximum is
mostly from video networks. The MDC has no rates: the zenithal hourly rate at
the maximum comes from the IMO Meteor Shower Calendar, which is only published
as a yearly PDF. ``IMO_ZHR`` holds those values and decides which showers are
returned.
"""

import re
from typing import Any

from django.core.cache import cache

LIST_URL = "https://www.ta3.sk/IAUC22DB/MDC2022/Roje/roje_lista.php"
FILE_BASE_URL = "https://www.ta3.sk/IAUC22DB/MDC2022/Etc/"
# The list is revised a few times a year.
CACHE_SECONDS = 60 * 60 * 24
TIMEOUT_SECONDS = 30

_CACHE_KEY = "caelus-iau-mdc-showers:3"
_FILE_PATTERN = re.compile(r"streamestablisheddata\d{4}\.txt")

# ZHR at the maximum, from the IMO 2026 Meteor Shower Calendar's working list of
# visual meteor showers, by IAU code; no open source publishes expected rates.
# Check against each year's calendar: https://www.imo.net/resources/calendar/
IMO_ZHR = {
    "QUA": 80,
    "LYR": 18,
    "ETA": 50,
    "CAP": 5,
    "SDA": 25,
    "PER": 100,
    "DRA": 5,
    "STA": 7,
    "ORI": 20,
    "NTA": 5,
    "LEO": 15,
    "GEM": 150,
    "URS": 10,
}


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


def parse_showers(text: str) -> list[dict[str, Any]]:
    """Return one entry per shower in ``IMO_ZHR``, from the MDC list's text."""
    by_code: dict[str, list[list[str]]] = {}
    for row in _rows(text):
        by_code.setdefault(row[3], []).append(row)

    showers = []
    for code, zhr in IMO_ZHR.items():
        solutions = by_code.get(code, [])
        main = _best(solutions, 10, 11, 12, 15)
        if main is None:
            continue
        activity = _best(solutions, 8, 9)
        drift = _best(solutions, 13, 14)
        showers.append(
            {
                "code": code,
                "name": main[6],
                "peak": _number(main[10]),
                "start": _number(activity[8]) if activity else None,
                "end": _number(activity[9]) if activity else None,
                "ra": _number(main[11]),
                "dec": _number(main[12]),
                "ra_drift": _number(drift[13]) if drift else 0.0,
                "dec_drift": _number(drift[14]) if drift else 0.0,
                "speed": _number(main[15]),
                "zhr": zhr,
            }
        )
    return showers


def get_showers() -> list[dict[str, Any]]:
    """Return the notable annual meteor showers with radiant, activity and ZHR.

    ``peak``, ``start`` and ``end`` are solar longitudes (degrees, J2000);
    ``start`` and ``end`` are null when no solution gives them. The drifts are
    degrees per degree of solar longitude.
    """
    cached = cache.get(_CACHE_KEY)
    if cached is not None:
        return cached

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

    showers = parse_showers(response.text)
    if not showers:
        raise IauMdcAPIError("The IAU MDC list has none of the expected showers.")

    cache.set(_CACHE_KEY, showers, timeout=CACHE_SECONDS)
    return showers
