"""Client for the IMO Meteor Shower Calendar's working list of visual showers.

The International Meteor Organization publishes its calendar once a year, only
as a PDF, and keeps every year in an archive at a fixed address
(``/files/meteor-shower/cal2026.pdf``; verified for 2024–2027, and the next
year's is there before the year starts). Its table "Working List of
Visual Meteor Showers" is the only open source of the expected zenithal hourly
rate (ZHR) and the visual activity period of each shower, so the table is read
from the PDF.

Verified live (cal2026.pdf and cal2027.pdf, same layout): pypdf extracts each
row as one line, e.g.
``Geminids (004 GEM) Dec 04–Dec 20 Dec 14 262 .◦2 112 ◦ +33◦ 35 2.6 150``:
name, IAU number and code, activity from–to, date of maximum, solar longitude
of the maximum (``262 .◦2`` is 262.2°, ``128 ◦`` is 128°), radiant RA and Dec
at the maximum, V∞ (km/s), population index r and ZHR (``110+`` when it may
be higher).

This year's calendar is read; last year's if this year's cannot be. If neither
can, the last list that could is used, and before any has been read the copy
in ``caelus/data/imo_working_list.json``, so the showers and their rates never
disappear; the failure is logged.
"""

import datetime
import io
import json
import logging
import re
from pathlib import Path
from typing import Any

from django.core.cache import cache

logger = logging.getLogger(__name__)

CALENDAR_URL = "https://www.imo.net/files/meteor-shower/cal{year}.pdf"
# A copy of the latest working list that ships with the code, used only when
# the IMO has never been readable since the cache was emptied.
SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "data" / "imo_working_list.json"
# The calendar is published once a year; the PDF is about 1 MB.
CACHE_SECONDS = 60 * 60 * 24 * 30
TIMEOUT_SECONDS = 30

_CACHE_KEY = "caelus-imo-working-list:1"
# The last list that could be read, kept until a newer one replaces it.
_LAST_KEY = "caelus-imo-working-list:last"

_MONTHS = {
    name: number
    for number, name in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1
    )
}
_DATE = r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})"
_ROW = re.compile(
    r"^(?P<name>.+?)\s*\(\d{3}\s+(?P<code>[A-Z]{3})\)\s+"
    rf"{_DATE}\s*[–-]\s*{_DATE}\s+{_DATE}\s+"
    r"(?P<peak>\d+)\s*(?:\.\s*◦\s*(?P<fraction>\d+)|◦)\s+"
    r"(?P<ra>\d+)\s*◦\s+(?P<dec>[+−-]\d+)\s*◦\s+"
    r"(?P<speed>\d+)\s+[\d.]+\s+(?P<zhr>\d+)\+?\s*$"
)


class ImoAPIError(RuntimeError):
    """Raised when no IMO working list can be read."""


def _solar_longitude(month: int, day: int, year: int) -> float:
    from caelus.services import events

    moment = datetime.datetime(year, month, day, 12, tzinfo=datetime.timezone.utc)
    return events._solar_longitude(events._time(moment)) % 360


def parse_working_list(text: str, year: int) -> list[dict[str, Any]]:
    """Return the rows of the working list in the calendar's text.

    ``start``, ``end`` and ``peak`` are solar longitudes (degrees, J2000); the
    dates are converted with the calendar's year, which matters only to a
    fraction of a degree.
    """
    rows = []
    for line in text.splitlines():
        match = _ROW.match(line.strip())
        # Daytime showers ("Dayt. Arietids") are only seen by radio, not at night by eye.
        if not match or match.group("name").startswith("Dayt."):
            continue
        start_month, start_day, end_month, end_day = (
            match.group(3), match.group(4), match.group(5), match.group(6),
        )
        fraction = match.group("fraction")
        rows.append(
            {
                "code": match.group("code"),
                "name": match.group("name").strip(),
                "start": _solar_longitude(_MONTHS[start_month], int(start_day), year),
                "end": _solar_longitude(_MONTHS[end_month], int(end_day), year),
                "peak": float(f"{match.group('peak')}.{fraction}" if fraction else match.group("peak")),
                "ra": float(match.group("ra")),
                "dec": float(match.group("dec").replace("−", "-")),
                "speed": float(match.group("speed")),
                "zhr": int(match.group("zhr")),
            }
        )
    return rows


def _read_calendar(year: int) -> list[dict[str, Any]]:
    """The working list of one year's calendar from the IMO's archive."""
    import requests
    from pypdf import PdfReader

    try:
        response = requests.get(CALENDAR_URL.format(year=year), timeout=TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise ImoAPIError("Could not reach the IMO.") from exc
    if not response.ok:
        raise ImoAPIError(f"The IMO returned HTTP {response.status_code} for the calendar {year}.")
    try:
        reader = PdfReader(io.BytesIO(response.content))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:  # pypdf raises several kinds of errors for a broken file
        raise ImoAPIError(f"The IMO calendar {year} could not be read: {exc}") from exc
    rows = parse_working_list(text, year)
    if not rows:
        raise ImoAPIError(f"The IMO calendar {year} has no working list that could be read.")
    return rows


def get_working_list() -> list[dict[str, Any]]:
    """Return the working list from this year's calendar, or last year's.

    When neither can be read, the last list that could is used, and before any
    has been read the copy that ships with the code, so the showers and their
    rates are always there; the failure is logged.
    """
    cached = cache.get(_CACHE_KEY)
    if cached is not None:
        return cached

    year = datetime.date.today().year
    try:
        try:
            rows = _read_calendar(year)
        except ImoAPIError as exc:
            logger.warning("imo: calendar %d: %s; trying %d", year, exc, year - 1)
            rows = _read_calendar(year - 1)
    except ImoAPIError as exc:
        last = cache.get(_LAST_KEY)
        if last is None:
            last = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
            logger.warning("imo: using the shipped working list: %s", exc)
        else:
            logger.warning("imo: using the last working list that could be read: %s", exc)
        # Try again in a day rather than in a month.
        cache.set(_CACHE_KEY, last, timeout=60 * 60 * 24)
        return last

    cache.set(_CACHE_KEY, rows, timeout=CACHE_SECONDS)
    cache.set(_LAST_KEY, rows, timeout=None)
    return rows
