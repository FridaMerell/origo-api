"""Notable sky events, ported from the frontend's ``app/caelus/ui/sky/events.ts``.

Uses the Python port of Astronomy Engine, the same library and version as the
frontend, so a warning names the same event the map shows. Ordinary full moons
are left out, as on the map's calendar disc; everything else on the disc is
notable.

Unlike the frontend, which computes a whole year at once, :func:`events_between`
searches only the given window, so a daily job stays cheap.
"""

import datetime
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

import astronomy

# Caelus's users are in Sweden (SMHI's forecast area); calendar months and days
# are counted here, as the frontend counts them in the browser's zone.
TIME_ZONE = ZoneInfo("Europe/Stockholm")

# The showers worth waiting for; the faintest only show on the map while active.
NOTABLE_ZHR = 10
# A full moon closer than this is a supermoon.
SUPERMOON_KM = 360_000

SWEDISH_SHOWER_NAMES = {
    "QUA": "Kvadrantiderna",
    "LYR": "Lyriderna",
    "ETA": "Eta Akvariderna",
    "CAP": "Alfa Capricorniderna",
    "SDA": "Södra delta Akvariderna",
    "PER": "Perseiderna",
    "DRA": "Draconiderna",
    "STA": "Södra Tauriderna",
    "ORI": "Orioniderna",
    "NTA": "Norra Tauriderna",
    "LEO": "Leoniderna",
    "GEM": "Geminiderna",
    "URS": "Ursiderna",
}

PLANETS = [
    (astronomy.Body.Mars, "Mars"),
    (astronomy.Body.Jupiter, "Jupiter"),
    (astronomy.Body.Saturn, "Saturnus"),
]
INNER = [
    (astronomy.Body.Mercury, "Merkurius"),
    (astronomy.Body.Venus, "Venus"),
]
ECLIPSE_KIND = {
    astronomy.EclipseKind.Penumbral: "Halvskuggförmörkelse",
    astronomy.EclipseKind.Partial: "Partiell",
    astronomy.EclipseKind.Annular: "Ringformig",
    astronomy.EclipseKind.Total: "Total",
}

_J2000 = datetime.datetime(2000, 1, 1, 12, tzinfo=datetime.timezone.utc)
_DAY = datetime.timedelta(days=1)


@dataclass(frozen=True)
class SkyEvent:
    time: datetime.datetime
    title: str
    detail: str


def _time(moment: datetime.datetime) -> astronomy.Time:
    return astronomy.Time((moment - _J2000) / _DAY)


def _datetime(time: astronomy.Time) -> datetime.datetime:
    return _J2000 + datetime.timedelta(days=time.ut)


def _solar_longitude(time: astronomy.Time) -> float:
    """The Sun's longitude for J2000, as the IAU lists the showers."""
    return astronomy.SunPosition(time).elon - 1.3969713 * time.ut / 36525


def shower_name(shower: dict[str, Any]) -> str:
    return SWEDISH_SHOWER_NAMES.get(shower["code"], shower["name"])


def events_between(
    start: datetime.datetime,
    end: datetime.datetime,
    latitude: float,
    longitude: float,
    showers: list[dict[str, Any]],
) -> list[SkyEvent]:
    """The notable events from ``start`` up to ``end`` for the place, in order.

    ``start`` and ``end`` are timezone-aware; ``showers`` is the list from
    :func:`caelus.services.iau_mdc.get_showers`.
    """
    begin = _time(start)
    days = (end - start) / _DAY
    observer = astronomy.Observer(latitude, longitude, 0)
    events: list[SkyEvent] = []

    def add(time: astronomy.Time, title: str, detail: str = ""):
        events.append(SkyEvent(_datetime(time), title, detail))

    for year in sorted({start.year, end.year}):
        seasons = astronomy.Seasons(year)
        add(seasons.mar_equinox, "Vårdagjämning", "Dag och natt är lika långa")
        add(seasons.jun_solstice, "Sommarsolstånd", "Årets längsta dag")
        add(seasons.sep_equinox, "Höstdagjämning", "Dag och natt är lika långa")
        add(seasons.dec_solstice, "Vintersolstånd", "Årets längsta natt")

    # A shower's maximum is when the Sun reaches its longitude. The list gives it
    # for J2000 and the search uses the equinox of date, so precession is added.
    for shower in showers:
        if shower["zhr"] < NOTABLE_ZHR:
            continue
        precession = (
            shower["peak"] - _solar_longitude(begin) + astronomy.SunPosition(begin).elon
        )
        peak = astronomy.SearchSunLongitude(precession % 360, begin, days)
        if peak is not None:
            add(
                peak,
                f"{shower_name(shower)}s maximum",
                f"Upp till {shower['zhr']} meteorer i timmen",
            )

    # Full moons; the second in the same calendar month is a blue moon. Ordinary
    # full moons are not notable.
    moon = astronomy.SearchMoonPhase(180, begin, days)
    while moon is not None and _datetime(moon) < end:
        local = _datetime(moon).astimezone(TIME_ZONE)
        month_start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        first = astronomy.SearchMoonPhase(180, _time(month_start), 32)
        blue = first is not None and first.ut < moon.ut - 1
        distance = astronomy.GeoMoon(moon).Length() * astronomy.KM_PER_AU
        near = distance < SUPERMOON_KM
        if blue or near:
            add(
                moon,
                "Blå supermåne" if blue and near else "Blå måne" if blue else "Supermåne",
                "Andra fullmånen i samma månad"
                if blue
                else f"Månen är nära jorden, {round(distance / 1000) * 1000} km bort",
            )
        moon = astronomy.SearchMoonPhase(180, moon.AddDays(1), days)

    eclipse = astronomy.SearchLunarEclipse(begin)
    while _datetime(eclipse.peak) < end:
        # An eclipse while the Moon is below the horizon is not seen from here.
        moon_position = astronomy.Equator(
            astronomy.Body.Moon, eclipse.peak, observer, True, True
        )
        horizon = astronomy.Horizon(
            eclipse.peak,
            observer,
            moon_position.ra,
            moon_position.dec,
            astronomy.Refraction.Airless,
        )
        if horizon.altitude > 0:
            add(
                eclipse.peak,
                "Halvskuggförmörkelse av månen"
                if eclipse.kind == astronomy.EclipseKind.Penumbral
                else f"{ECLIPSE_KIND[eclipse.kind]} månförmörkelse",
                f"Totalitet i {round(eclipse.sd_total * 2)} minuter"
                if eclipse.kind == astronomy.EclipseKind.Total
                else "",
            )
        eclipse = astronomy.NextLunarEclipse(eclipse.peak)

    # Solar eclipses seen from the place, with the Sun up.
    solar = astronomy.SearchLocalSolarEclipse(begin, observer)
    while _datetime(solar.peak.time) < end:
        if solar.peak.altitude > 0:
            add(
                solar.peak.time,
                f"{ECLIPSE_KIND[solar.kind]} solförmörkelse",
                f"{round(solar.obscuration * 100)} % av solen skyms",
            )
        solar = astronomy.NextLocalSolarEclipse(solar.peak.time, observer)

    # The outer planets at opposition: closest, brightest and up all night.
    for body, name in PLANETS:
        time = astronomy.SearchRelativeLongitude(body, 0, begin)
        while _datetime(time) < end:
            add(time, f"{name} i opposition", "Uppe hela natten och som ljusast")
            time = astronomy.SearchRelativeLongitude(body, 0, time.AddDays(1))

    # Mercury and Venus are best seen farthest from the Sun.
    for body, name in INNER:
        elongation = astronomy.SearchMaxElongation(body, begin)
        while _datetime(elongation.time) < end:
            sky = (
                "morgonhimlen"
                if elongation.visibility == astronomy.Visibility.Morning
                else "kvällshimlen"
            )
            add(
                elongation.time,
                f"{name} längst från solen",
                f"{round(elongation.elongation)}° från solen, på {sky}",
            )
            elongation = astronomy.SearchMaxElongation(body, elongation.time.AddDays(1))

    return sorted(
        (event for event in events if start <= event.time < end),
        key=lambda event: event.time,
    )
