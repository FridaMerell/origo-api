"""Client for NOAA SWPC's planetary K-index product.

One public JSON file, no key:
https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json

Verified live: a list of ``{"time_tag", "kp", "observed", "noaa_scale"}``
covering roughly the last week and the next three days in 3-hour steps.
``time_tag`` is UTC without an offset, ``observed`` is "observed",
"estimated" or "predicted", and ``noaa_scale`` is null below a G1 storm.
"""

from typing import Any

from django.core.cache import cache

KP_INDEX_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json"
# The file changes at most every few hours; the Kp value itself is 3-hourly.
CACHE_SECONDS = 60 * 15
TIMEOUT_SECONDS = 15

_CACHE_KEY = "caelus-noaa-kp-index:1"


class NoaaAPIError(RuntimeError):
    """Raised when NOAA SWPC cannot serve a valid response."""


def get_kp_index() -> list[dict[str, Any]]:
    """Return the planetary Kp index, oldest first, observed and predicted.

    Each entry is ``{"time", "kp", "status", "noaa_scale"}`` with ``time`` as
    an ISO 8601 UTC timestamp marking the start of the 3-hour period.
    """
    cached = cache.get(_CACHE_KEY)
    if cached is not None:
        return cached

    import requests

    try:
        response = requests.get(
            KP_INDEX_URL, headers={"Accept": "application/json"}, timeout=TIMEOUT_SECONDS
        )
    except requests.RequestException as exc:
        raise NoaaAPIError("Could not reach NOAA SWPC.") from exc
    if not response.ok:
        raise NoaaAPIError(f"NOAA SWPC returned HTTP {response.status_code}.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise NoaaAPIError("NOAA SWPC returned invalid JSON.") from exc

    entries = [
        {
            "time": f"{row['time_tag']}Z",
            "kp": row["kp"],
            "status": row.get("observed"),
            "noaa_scale": row.get("noaa_scale"),
        }
        for row in (payload if isinstance(payload, list) else [])
        if isinstance(row, dict)
        and isinstance(row.get("time_tag"), str)
        and isinstance(row.get("kp"), (int, float))
    ]
    if not entries:
        raise NoaaAPIError("NOAA SWPC returned no Kp values.")

    cache.set(_CACHE_KEY, entries, timeout=CACHE_SECONDS)
    return entries
