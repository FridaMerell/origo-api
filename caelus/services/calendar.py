"""The notable sky events for a place as an iCalendar feed.

Calendar apps subscribe to the feed and fetch it again on their own, so it
always covers the coming year. The events are those of
:func:`caelus.services.events.events_between`, the same as the evening
warnings.
"""

import datetime
import hashlib
import logging

from django.core.cache import cache
from django.utils import timezone

from caelus.services import events, iau_mdc

logger = logging.getLogger(__name__)

DAYS_AHEAD = 365
# One decimal (about 10 km) is enough for which eclipses are seen, lets nearby
# subscribers share a cache entry and keeps the exact home out of the URL.
COORDINATE_DECIMALS = 1
# The events only move when the day changes; the meteor showers are cached for a day.
CACHE_SECONDS = 60 * 60 * 6


def _uid(event: events.SkyEvent) -> str:
    """A stable id, so that a calendar updates an event instead of adding it twice."""
    digest = hashlib.sha1(f"{event.title}|{event.time.isoformat()}".encode()).hexdigest()
    return f"{digest}@caelus.origo"


def calendar_feed(latitude: float, longitude: float) -> bytes:
    """Return the iCalendar file of the coming year's events for a place."""
    latitude = round(latitude, COORDINATE_DECIMALS)
    longitude = round(longitude, COORDINATE_DECIMALS)
    today = timezone.now().astimezone(events.TIME_ZONE).date()
    cache_key = f"caelus-calendar:1:{latitude}:{longitude}:{today.isoformat()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    from icalendar import Calendar, Event

    try:
        showers = iau_mdc.get_showers()
    except iau_mdc.IauMdcAPIError as exc:
        # The other events are still worth having; the next fetch tries again.
        logger.warning("calendar_feed: no meteor showers: %s", exc)
        showers = []

    start = datetime.datetime.combine(today, datetime.time(), tzinfo=events.TIME_ZONE)
    end = start + datetime.timedelta(days=DAYS_AHEAD)
    stamp = timezone.now()

    calendar = Calendar()
    calendar.add("prodid", "-//Origo//Caelus//SV")
    calendar.add("version", "2.0")
    calendar.add("x-wr-calname", "Händelser på himlen")
    calendar.add("x-wr-timezone", str(events.TIME_ZONE))
    # How often a subscribing app should fetch the feed again.
    calendar.add("refresh-interval", datetime.timedelta(days=1), parameters={"VALUE": "DURATION"})
    calendar.add("x-published-ttl", "P1D")
    for sky_event in events.events_between(start, end, latitude, longitude, showers):
        entry = Event()
        entry.add("uid", _uid(sky_event))
        entry.add("dtstamp", stamp)
        entry.add("dtstart", sky_event.time)
        entry.add("summary", sky_event.title)
        if sky_event.detail:
            entry.add("description", sky_event.detail)
        calendar.add_component(entry)

    body = calendar.to_ical()
    # Without showers the feed is cached briefly, so they come back soon.
    cache.set(cache_key, body, timeout=CACHE_SECONDS if showers else 60 * 15)
    return body
