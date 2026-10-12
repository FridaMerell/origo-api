"""Client for SMHI's open point forecast (SNOW1g v1), cloud cover only.

No key. SNOW1g replaced PMP3g, which was shut down on 31 March 2026:
https://opendata.smhi.se/apidocs/metfcst/index.html

Verified live: the response is ``{"createdTime", "referenceTime",
"geometry", "timeSeries"}``, each time step carries its values flat under
``data``, cloud cover is in octas (0-8), and a point outside the forecast
area answers HTTP 404. The forecast is the nearest point on a ~2.5 km grid,
hourly for the first days and coarser after that.
"""

from typing import Any

from django.core.cache import cache

FORECAST_URL = (
    "https://opendata-download-metfcst.smhi.se/api/category/snow1g/version/1"
    "/geotype/point/lon/{longitude}/lat/{latitude}/data.json?parameters={parameters}"
)
# SMHI publishes a new forecast about once an hour.
CACHE_SECONDS = 60 * 30
TIMEOUT_SECONDS = 15
# SMHI accepts at most six decimals; two (~1 km) is finer than the grid and
# lets nearby requests share a cache entry.
COORDINATE_DECIMALS = 2

# Our name -> SMHI's parameter name. Only these are requested.
_PARAMETERS = {
    "total": "cloud_area_fraction",
    "low": "low_type_cloud_area_fraction",
    "medium": "medium_type_cloud_area_fraction",
    "high": "high_type_cloud_area_fraction",
}
# SMHI's placeholder for a missing value.
_MISSING_VALUE = 9999

_MISSING = object()


class SmhiAPIError(RuntimeError):
    """Raised when SMHI's forecast API cannot serve a valid response."""


def _octas(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or value == _MISSING_VALUE:
        return None
    return value


def get_cloud_cover(latitude: float, longitude: float) -> dict[str, Any] | None:
    """Return the cloud cover forecast for a point, or None outside SMHI's area.

    The result is ``{"reference_time", "series"}`` where each step in
    ``series`` is ``{"time", "total", "low", "medium", "high"}``: an ISO 8601
    UTC timestamp and cloud cover in octas (0 clear, 8 overcast), None when
    SMHI has no value.
    """
    latitude = round(latitude, COORDINATE_DECIMALS)
    longitude = round(longitude, COORDINATE_DECIMALS)
    cache_key = f"caelus-smhi-cloud-cover:1:{latitude}:{longitude}"
    cached = cache.get(cache_key, _MISSING)
    if cached is not _MISSING:
        return cached

    import requests

    try:
        response = requests.get(
            # Verified live: the commas must be literal. Passed through
            # ``params`` they are sent as %2C and only the first name is honoured.
            FORECAST_URL.format(
                latitude=latitude,
                longitude=longitude,
                parameters=",".join(_PARAMETERS.values()),
            ),
            headers={"Accept": "application/json"},
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise SmhiAPIError("Could not reach SMHI's forecast API.") from exc

    result = None
    if response.status_code != 404:
        if not response.ok:
            raise SmhiAPIError(f"SMHI's forecast API returned HTTP {response.status_code}.")
        try:
            payload = response.json()
        except ValueError as exc:
            raise SmhiAPIError("SMHI's forecast API returned invalid JSON.") from exc
        steps = payload.get("timeSeries") if isinstance(payload, dict) else None
        if not isinstance(steps, list):
            raise SmhiAPIError("SMHI's forecast API returned no time series.")
        result = {
            "reference_time": payload.get("referenceTime"),
            "series": [
                {
                    "time": step["time"],
                    **{
                        name: _octas((step.get("data") or {}).get(parameter))
                        for name, parameter in _PARAMETERS.items()
                    },
                }
                for step in steps
                if isinstance(step, dict) and isinstance(step.get("time"), str)
            ],
        }

    cache.set(cache_key, result, timeout=CACHE_SECONDS)
    return result
