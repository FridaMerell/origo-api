"""Client for Svenska kyrkan's PlatserAPI (v4) and Kyrkobyggnadsregistret (KBR API v1).

Documented at https://api.svenskakyrkan.se/platser/v4/doc/ and
https://api.svenskakyrkan.se/doc/kyrkobyggnadsregistret/. The API key is sent
in the ``SvkAuthSvc-ApiKey`` header and never leaves the server.

Platser is the source of a church: it is what Apsis searches, and its place ID
is the only thing stored on a Post. Everything else is read live and cached.

KBR is the register of the building itself and adds facts Platser lacks. The
two share no ID (verified live: KBR's ``facilityPartId`` is not a Platser
place ID), so the building is found by name and position and left out when
there is no safe match. KBR's documentation does not list a building's fields;
it refers to calling the API with ``fields=*``, so the building is passed on
as KBR returned it.
"""

from hashlib import sha256
from html import unescape
from typing import Any
from urllib.parse import quote

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.utils.html import strip_tags

from tempus.services.geo import haversine_m, sweref99tm_to_wgs84

PLATSER_BASE_URL = "https://api.svenskakyrkan.se/platser/v4"
KBR_BASE_URL = "https://api.svenskakyrkan.se/kbr/api"
PLACE_CACHE_SECONDS = 60 * 60 * 24
SEARCH_CACHE_SECONDS = 60 * 60
SEARCH_LIMIT = 10
SUMMARY_BATCH_SIZE = 100
TIMEOUT_SECONDS = 15
# Without these, owner, categories and tags come back as bare IDs.
_EXPAND = "owner,categories,tags"
# How far a KBR building may lie from the Platser place and still be the same church.
MATCH_RADIUS_METRES = 500

# Part of every cache key: bump it when _summary's shape changes, so entries
# cached with the previous shape are not served.
_SUMMARY_VERSION = 5

_MISSING = object()


class SvenskaKyrkanConfigurationError(RuntimeError):
    """Raised when SVENSKAKYRKAN_TOKEN is not configured."""


class SvenskaKyrkanAPIError(RuntimeError):
    """Raised when Svenska kyrkan's API cannot serve a valid response."""


def _get(base_url: str, path: str, params: dict[str, Any]) -> Any:
    """Return the decoded JSON body, or None when the resource does not exist."""
    import requests

    token = getattr(settings, "SVENSKAKYRKAN_TOKEN", "")
    if not token:
        raise SvenskaKyrkanConfigurationError("Configure SVENSKAKYRKAN_TOKEN.")
    try:
        response = requests.get(
            f"{base_url}{path}",
            headers={"Accept": "application/json", "SvkAuthSvc-ApiKey": token},
            params=params,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise SvenskaKyrkanAPIError("Could not reach Svenska kyrkan's API.") from exc
    if response.status_code == 404:
        return None
    if not response.ok:
        raise SvenskaKyrkanAPIError(
            f"Svenska kyrkan's API returned HTTP {response.status_code}."
        )
    try:
        return response.json()
    except ValueError as exc:
        raise SvenskaKyrkanAPIError("Svenska kyrkan's API returned invalid JSON.") from exc


def _plain(value: Any) -> str:
    """Platser's texts carry stray HTML; keep the text and its line breaks."""
    return unescape(strip_tags(value)).strip() if isinstance(value, str) else ""


_DAYS = ("mo", "tu", "we", "th", "fr", "sa", "su")

# placeDetails flags Apsis passes on, keyed by the name callers see.
_FACILITIES = {
    "toilet": ("hasToilet",),
    "accessible_toilet": ("accessibility", "toiletAccessible"),
    "cafe": ("hasCafe",),
    "wifi": ("hasWifi",),
    "parking": ("hasParking",),
    "charging_station": ("hasChargingStation",),
    "hearing_loop": ("accessibility", "hasHearingLoop"),
    "ramp": ("accessibility", "hasRamp"),
}


def _names(items: Any) -> list[str]:
    """Categories and tags only carry a name when the request expands them."""
    return [
        _plain(item.get("name"))
        for item in items or []
        if isinstance(item, dict) and _plain(item.get("name"))
    ]


def _flag(details: Any, path: tuple[str, ...]) -> bool:
    for key in path:
        details = details.get(key) if isinstance(details, dict) else None
    return details is True


def _phone(phone: Any) -> str:
    """Platser splits a number into country code, area code and local number."""
    if not isinstance(phone, dict) or not phone.get("number"):
        return ""
    area = f"{phone.get('areaCode')} " if phone.get("areaCode") else ""
    country = phone.get("countryCode")
    return f"+{country} {area}{phone['number']}" if country else f"0{area}{phone['number']}"


def _open_hours(open_hours: Any) -> list[dict[str, Any]]:
    """Return the period that applies today as runs of days sharing the same hours.

    Verified live: ``openHours`` is ``{"periods": [...]}`` (the documentation
    shows a bare list), with ISO dates that may be missing at either end.
    """
    periods = open_hours.get("periods") if isinstance(open_hours, dict) else open_hours
    today = timezone.localdate().isoformat()
    current = next(
        (
            period
            for period in periods or []
            if isinstance(period, dict)
            and (period.get("validFrom") or "") <= today
            and today <= (period.get("validTo") or "9999")
        ),
        None,
    )
    if current is None:
        return []

    runs: list[dict[str, Any]] = []
    days = current.get("days") or {}
    for day in _DAYS:
        hours = [
            f"{slot.get('from')}–{slot.get('to')}"
            for slot in days.get(day) or []
            if isinstance(slot, dict) and slot.get("from") and slot.get("to")
        ]
        if runs and runs[-1]["hours"] == hours:
            runs[-1]["to"] = day
        else:
            runs.append({"from": day, "to": day, "hours": hours})
    return [run for run in runs if run["hours"]]


def _summary(place: dict[str, Any]) -> dict[str, Any]:
    """Reduce a Platser place to the fields Apsis shows."""
    # GeoJSON order: longitude, latitude.
    coordinates = ((place.get("geolocation") or {}).get("geometry") or {}).get("coordinates")
    longitude = latitude = None
    if isinstance(coordinates, (list, tuple)) and len(coordinates) >= 2:
        longitude, latitude = round(coordinates[0], 6), round(coordinates[1], 6)

    owner = place.get("owner") or {}
    location = place.get("geolocationInfo") or {}
    visiting = place.get("visitingInfo") or {}
    contact = place.get("contactInfo") or {}
    return {
        "id": str(place.get("id", "")),
        "name": _plain(place.get("name")),
        "owner_name": _plain(owner.get("name")),
        "municipality": _plain(location.get("municipality")),
        "county": _plain(location.get("county")),
        "latitude": latitude,
        "longitude": longitude,
        "short_description": _plain(place.get("shortDescription")),
        # Markdown.
        "long_description": _plain(place.get("longDescription")),
        "address": _plain(visiting.get("address")),
        "postal_code": _plain(visiting.get("postalCode")),
        "city": _plain(visiting.get("city")),
        "url": _plain(contact.get("url")),
        "email": _plain(contact.get("email")),
        "phone": _phone(contact.get("phone")),
        "categories": _names(place.get("categories")),
        "tags": _names(place.get("tags")),
        "open_hours": _open_hours(place.get("openHours")),
        "facilities": [
            name for name, path in _FACILITIES.items() if _flag(place.get("placeDetails"), path)
        ],
        # Verified live: this key sees no images, audio or video, only links.
        "links": [
            {"title": _plain(link.get("title")), "url": _plain(link.get("url"))}
            for link in (place.get("media") or {}).get("links") or []
            if isinstance(link, dict) and link.get("url")
        ],
    }


def _building(summary: dict[str, Any]) -> dict[str, Any] | None:
    """Return the KBR building of a Platser place, as KBR returned it, or None.

    Several churches share a name (verified live: KBR has three "Dalby
    kyrka"), so a building only counts when it also lies at the place.
    """
    if not summary["name"] or summary["latitude"] is None or summary["longitude"] is None:
        return None
    try:
        payload = _get(
            KBR_BASE_URL,
            "/byggnader",
            {"kyrka": "true", "namn": summary["name"], "fields": "*", "limit": 100},
        )
    except SvenskaKyrkanAPIError:
        # The building facts are an addition; the place is still worth showing.
        return None

    for building in payload if isinstance(payload, list) else []:
        if not isinstance(building, dict):
            continue
        # Verified live: xKoordinat is the SWEREF 99 TM easting, yKoordinat the northing.
        easting, northing = building.get("xKoordinat"), building.get("yKoordinat")
        if not isinstance(easting, (int, float)) or not isinstance(northing, (int, float)):
            continue
        longitude, latitude = sweref99tm_to_wgs84(easting, northing)
        distance = haversine_m(summary["latitude"], summary["longitude"], latitude, longitude)
        if distance <= MATCH_RADIUS_METRES:
            return building
    return None


def get_place(place_id: str) -> dict[str, Any] | None:
    """Return one Platser place by its ID, or None when it does not exist.

    Unlike a search hit, the result also carries ``building``: the matching
    KBR building, or None when there is no safe match.
    """
    cache_key = f"svenska-kyrkan-place:{_SUMMARY_VERSION}:{place_id}"
    cached = cache.get(cache_key, _MISSING)
    if cached is not _MISSING:
        return cached

    place = _get(PLATSER_BASE_URL, f"/place/{quote(place_id, safe='')}", {"expand": _EXPAND})
    result = None
    if isinstance(place, dict):
        result = _summary(place)
        result["building"] = _building(result)
    cache.set(cache_key, result, timeout=PLACE_CACHE_SECONDS)
    return result


def search_places(query: str) -> list[dict[str, Any]]:
    """Return churches and chapels whose name contains every word in ``query``."""
    # "," separates alternative values and "!" inverts a term in Platser's
    # search syntax; neither belongs in a church name.
    term = " ".join(query.replace(",", " ").replace("!", " ").split())
    if not term:
        return []

    cache_key = f"svenska-kyrkan-search:{_SUMMARY_VERSION}:{sha256(term.casefold().encode('utf-8')).hexdigest()}"
    cached = cache.get(cache_key, _MISSING)
    if cached is not _MISSING:
        return cached

    payload = _get(
        PLATSER_BASE_URL,
        "/place",
        {
            "is": "churchandchapel",
            "name": f"~{term}",
            "limit": SEARCH_LIMIT,
            "expand": _EXPAND,
        },
    )
    hits = payload.get("results") or [] if isinstance(payload, dict) else []
    results = [_summary(place) for place in hits if isinstance(place, dict)]
    cache.set(cache_key, results, timeout=SEARCH_CACHE_SECONDS)
    return results


def get_place_summaries(place_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Return the summaries of several places, keyed by ID, without their buildings.

    Uncached places are fetched in one request (Platser's ``id=a,b,c`` filter),
    so a list of posts costs one upstream call instead of one per post.
    Unknown IDs are simply absent from the result.
    """
    keys = {
        place_id: f"svenska-kyrkan-place-summary:{_SUMMARY_VERSION}:{place_id}"
        for place_id in dict.fromkeys(place_ids)
    }
    cached = cache.get_many(keys.values())
    summaries = {
        place_id: cached[key] for place_id, key in keys.items() if cached.get(key) is not None
    }
    missing = [place_id for place_id, key in keys.items() if key not in cached]
    for start in range(0, len(missing), SUMMARY_BATCH_SIZE):
        batch = missing[start : start + SUMMARY_BATCH_SIZE]
        payload = _get(
            PLATSER_BASE_URL,
            "/place",
            # "*" also returns places that are not churches, should a post point at one.
            {"id": ",".join(batch), "is": "*", "limit": len(batch), "expand": _EXPAND},
        )
        found = {
            str(place.get("id")): _summary(place)
            for place in (payload.get("results") or [] if isinstance(payload, dict) else [])
            if isinstance(place, dict)
        }
        summaries.update(found)
        # Unknown IDs are cached as None so they are not asked for again.
        cache.set_many(
            {keys[place_id]: found.get(place_id) for place_id in batch},
            timeout=PLACE_CACHE_SECONDS,
        )
    return summaries
