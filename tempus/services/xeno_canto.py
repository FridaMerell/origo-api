"""Client for the xeno-canto API v3: sound recordings per species.

Endpoint: ``GET https://xeno-canto.org/api/3/recordings?query=...&key=...``.
The key is sent as the ``key`` query parameter (from XENO_CANTO_API_KEY) and
never leaves the server. A search is a set of tags (``gen:``, ``sp:``,
``ssp:``, ``type:``, ``q:``); recordings are returned a page at a time.

Every recording carries a Creative Commons licence that requires crediting
the recordist, so the licence and recordist are always passed on.
"""

from hashlib import sha256
from typing import Any

from django.conf import settings
from django.core.cache import cache

BASE_URL = "https://xeno-canto.org/api/3"
TIMEOUT_SECONDS = 20
CACHE_SECONDS = 60 * 60 * 6
# xeno-canto accepts 50-500 recordings per page.
PER_PAGE = 50

# Part of every cache key: bump it when _recording's shape changes.
_RECORDING_VERSION = 2


class XenoCantoConfigurationError(RuntimeError):
    """Raised when XENO_CANTO_API_KEY is not configured."""


class XenoCantoAPIError(RuntimeError):
    """Raised when xeno-canto cannot serve a valid response."""


def _get(path: str, params: dict[str, Any]) -> dict[str, Any]:
    import requests

    key = getattr(settings, "XENO_CANTO_API_KEY", "")
    if not key:
        raise XenoCantoConfigurationError("Configure XENO_CANTO_API_KEY.")
    try:
        response = requests.get(
            f"{BASE_URL}{path}",
            params={**params, "key": key},
            headers={"Accept": "application/json"},
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise XenoCantoAPIError("Could not reach xeno-canto.") from exc
    try:
        body = response.json()
    except ValueError as exc:
        raise XenoCantoAPIError(
            f"xeno-canto returned HTTP {response.status_code} without valid JSON."
        ) from exc
    if not response.ok or "error" in body:
        message = body.get("message") if isinstance(body, dict) else None
        raise XenoCantoAPIError(
            f"xeno-canto returned HTTP {response.status_code}: {message or 'unknown error'}"
        )
    return body


def _tag(name: str, value: str) -> str:
    """Tag values containing spaces must be quoted (e.g. type:"flight call")."""
    value = value.strip()
    return f'{name}:"{value}"' if " " in value else f"{name}:{value}"


def _https(url: Any) -> str:
    """Sonogram and file URLs may come back protocol-relative (//xeno-canto.org/...)."""
    if not isinstance(url, str) or not url:
        return ""
    return f"https:{url}" if url.startswith("//") else url


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _images(value: Any) -> dict[str, str]:
    """sono/osci: image URLs keyed by size (small, med, large, full)."""
    if not isinstance(value, dict):
        return {}
    return {size: _https(url) for size, url in value.items() if url}


def _recording(item: dict[str, Any]) -> dict[str, Any]:
    """Every field xeno-canto returns for a recording, under snake_case names."""
    return {
        "id": item.get("id"),
        "group": item.get("grp") or "",
        "genus": item.get("gen") or "",
        "species": item.get("sp") or "",
        "subspecies": item.get("ssp") or "",
        "scientific_name": " ".join(
            part for part in (item.get("gen"), item.get("sp"), item.get("ssp")) if part
        ),
        "english_name": item.get("en") or "",
        "recordist": item.get("rec") or "",
        "country": item.get("cnt") or "",
        "location": item.get("loc") or "",
        "latitude": _float(item.get("lat")),
        "longitude": _float(item.get("lon")),
        "altitude": item.get("alt") or "",
        "sound_type": item.get("type") or "",
        "sex": item.get("sex") or "",
        "stage": item.get("stage") or "",
        "method": item.get("method") or "",
        "page_url": _https(item.get("url")),
        "audio_url": _https(item.get("file")),
        "file_name": item.get("file-name") or "",
        "sonograms": _images(item.get("sono")),
        "oscillograms": _images(item.get("osci")),
        "licence_url": _https(item.get("lic")),
        "quality": item.get("q") or "",
        "length": item.get("length") or "",
        "time": item.get("time") or "",
        "date": item.get("date") or "",
        "uploaded": item.get("uploaded") or "",
        "also": item.get("also") or [],
        "remarks": item.get("rmk") or "",
        "animal_seen": item.get("animal-seen") or "",
        "playback_used": item.get("playback-used") or "",
        "temperature": item.get("temp") or "",
        "registration_number": item.get("regnr") or "",
        "automatic": item.get("auto") or "",
        "device": item.get("dvc") or "",
        "microphone": item.get("mic") or "",
        "sample_rate": item.get("smp") or "",
        "annotation_set": item.get("annotation-set"),
        "status": item.get("status"),
    }


def recordings_for_species(
    scientific_name: str,
    *,
    sound_type: str | None = None,
    quality: str | None = None,
    page: int = 1,
) -> dict[str, Any]:
    """Return one page of xeno-canto recordings for a species.

    ``scientific_name`` is "Genus species" or "Genus species subspecies".
    ``sound_type`` filters on xeno-canto's type tag (e.g. "song", "call"),
    ``quality`` on its rating A-E.
    """
    parts = scientific_name.split()
    if len(parts) < 2:
        raise ValueError("scientific_name must be 'Genus species'.")
    tags = [_tag("gen", parts[0]), _tag("sp", parts[1])]
    if len(parts) > 2:
        tags.append(_tag("ssp", parts[2]))
    if sound_type:
        tags.append(_tag("type", sound_type))
    if quality:
        tags.append(_tag("q", quality.upper()))
    query = " ".join(tags)

    cache_key = "xeno-canto:recordings:{}:{}".format(
        _RECORDING_VERSION, sha256(f"{query}|{page}".encode()).hexdigest()
    )
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    body = _get("/recordings", {"query": query, "page": page, "per_page": PER_PAGE})
    result = {
        "count": int(body.get("numRecordings") or 0),
        "page": int(body.get("page") or page),
        "num_pages": int(body.get("numPages") or 0),
        "recordings": [
            _recording(item) for item in body.get("recordings") or [] if isinstance(item, dict)
        ],
    }
    cache.set(cache_key, result, CACHE_SECONDS)
    return result
