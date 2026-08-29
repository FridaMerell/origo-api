"""Integration boundary for SLU Artdatabanken APIs.

Covers the products the project is subscribed to: the Species Observation
System (observations), the Dyntaxa Taxon Service (taxonomy) and Artfakta
(species information). Reporting observations *into* Artportalen needs the
separate "Artportalen - Species Observations Read and Write" product, which the
project does not have - see ``.claude/skills/artdatabanken-api/`` for the
request path.

Configuration lives in ``settings.ARTDATABANKEN`` (base URLs, per-product
subscription keys, timeout, user agent). Calls raise
:class:`ArtdatabankenConfigurationError` when a required key is missing and
:class:`ArtdatabankenAPIError` when the API responds with an error.

The exact response schemas for the taxon and species-information endpoints are
only fully specified in each product's OpenAPI document on the developer
portal; ``_normalize_taxon`` is deliberately defensive and the field mapping
should be confirmed against that document.
"""

import datetime
import logging
from typing import Any, Iterator, NotRequired, TypedDict

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from tempus.models import Species, SpeciesCategory

logger = logging.getLogger(__name__)

# Species Observation System search limits (portal FAQ).
SOS_MAX_TAKE = 1000
SOS_MAX_WINDOW = 10_000

# Taxon name-search result caps.
TAXON_SEARCH_DEFAULT_LIMIT = 20
TAXON_SEARCH_MAX_LIMIT = 50

# Dyntaxa taxon-category id for species rank (search returns species only).
TAXON_CATEGORY_SPECIES = 17

# A resolved category subtree (all taxa under one node, with names) is cached
# this long. The Dyntaxa tree barely moves, so this can be generous — it means
# one API call per category, then in-memory text filtering for every search.
TAXON_SUBTREE_CACHE_TTL = 24 * 60 * 60
# Depth requested from /childhierarchy — deep enough to reach every species.
TAXON_SUBTREE_LEVELS = 50


class ArtdatabankenConfigurationError(RuntimeError):
    """Raised when the external API integration has not been configured."""


class ArtdatabankenAPIError(RuntimeError):
    """Raised when an Artdatabanken API returns a non-success response."""

    def __init__(self, method: str, url: str, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"{method} {url} -> HTTP {status}: {body[:500]}")


class TaxonData(TypedDict):
    """Normalized taxon data returned by the API adapter."""

    dyntaxa_taxon_id: int
    scientific_name: str
    swedish_name: NotRequired[str]
    taxon_rank: NotRequired[str]
    parent_dyntaxa_taxon_id: NotRequired[int | None]
    is_active: NotRequired[bool]
    api_data: dict[str, Any]


# --------------------------------------------------------------------------- #
# Transport
# --------------------------------------------------------------------------- #
def _config() -> dict[str, Any]:
    return getattr(settings, "ARTDATABANKEN", {}) or {}


def _require(base_url_key: str, subscription_key: str) -> tuple[str, str]:
    config = _config()
    base_url = config.get(base_url_key)
    key = config.get(subscription_key)
    if not base_url or not key:
        raise ArtdatabankenConfigurationError(
            f"settings.ARTDATABANKEN needs {base_url_key!r} and {subscription_key!r}. "
            "Set the ARTDATABANKEN_* environment variables (see .env.example)."
        )
    return base_url.rstrip("/"), key


def _session():
    import requests  # optional dependency; only needed for live calls

    session = requests.Session()
    session.headers["User-Agent"] = _config().get(
        "USER_AGENT", "Tempus (+tempus.services.artdatabanken)"
    )
    return session


def _call(
    method: str,
    base_url_key: str,
    subscription_key: str,
    path: str,
    *,
    params: dict | None = None,
    json: Any = None,
) -> Any:
    base_url, key = _require(base_url_key, subscription_key)
    url = f"{base_url}/{path.lstrip('/')}"
    response = _session().request(
        method,
        url,
        params=params,
        json=json,
        headers={"Ocp-Apim-Subscription-Key": key},
        timeout=_config().get("TIMEOUT", 30),
    )
    if not response.ok:
        raise ArtdatabankenAPIError(method, url, response.status_code, response.text)
    if response.status_code == 204 or not response.content:
        return None
    return response.json()


# --------------------------------------------------------------------------- #
# Taxonomy (Dyntaxa Taxon Service)
# --------------------------------------------------------------------------- #
def _pick_names(raw: dict[str, Any]) -> tuple[str, str]:
    """Pull (scientific_name, swedish_name) from whatever shape ``raw`` uses.

    ``POST /taxa`` and ``GET /taxa/search`` items carry a ``names`` list of
    ``{name, nameShort, category|nameCategory: {value}, isRecommended}``;
    ``GET /taxa/names`` rows nest ``taxonInformation.recommended*Name``.
    """
    info = raw.get("taxonInformation") or {}
    scientific = (
        info.get("recommendedScientificName")
        or raw.get("recommendedScientificName")
        or raw.get("scientificName")
        or ""
    )
    swedish = (
        info.get("recommendedSwedishName")
        or raw.get("recommendedSwedishName")
        or raw.get("swedishName")
        or ""
    )
    sci_fallback = swe_fallback = ""
    for entry in raw.get("names") or raw.get("recommendedNames") or []:
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        name_category = entry.get("nameCategory") or entry.get("category") or {}
        category = name_category.get("value", "") if isinstance(name_category, dict) else ""
        short = str(
            entry.get("nameShort")
            or entry.get("culture")
            or entry.get("cultureCode")
            or ""
        ).lower()
        recommended = bool(entry.get("isRecommended"))
        if category == "ScientificName" or short in {"lat", "la"}:
            if recommended and not scientific:
                scientific = entry["name"]
            elif not sci_fallback:
                sci_fallback = entry["name"]
        elif category == "SwedishName" or short in {"swe", "sv", "sv-se"}:
            if recommended and not swedish:
                swedish = entry["name"]
            elif not swe_fallback:
                swe_fallback = entry["name"]
    return scientific or sci_fallback, swedish or swe_fallback


def _normalize_taxon(raw: dict[str, Any]) -> TaxonData:
    """Map a taxon-service payload onto :class:`TaxonData`.

    Handles ``TaxonDto`` (``POST /taxa``), ``TaxonSearchResultDto``
    (``GET /taxa/search``) and ``TaxonNameSearchResultDto`` (``GET /taxa/names``,
    where the taxon id is under ``taxonInformation`` and ``raw["id"]`` is a name
    id).
    """
    info = raw.get("taxonInformation") or {}
    taxon_id = (
        info.get("taxonId")
        or raw.get("taxonId")
        or raw.get("acceptedTaxonId")
        or (raw.get("id") if "taxonInformation" not in raw else None)
    )
    scientific_name, swedish_name = _pick_names(raw)

    category = raw.get("category")
    if isinstance(category, dict):
        taxon_rank = category.get("name") or category.get("value") or ""
    else:
        taxon_rank = str(category or raw.get("taxonRank") or "")

    status = raw.get("status")
    if isinstance(status, dict):
        is_active = status.get("value") == "Accepted"
    else:
        is_active = raw.get("isValid", raw.get("isActive", True))

    return TaxonData(
        dyntaxa_taxon_id=int(taxon_id),
        scientific_name=scientific_name,
        swedish_name=swedish_name,
        taxon_rank=taxon_rank,
        parent_dyntaxa_taxon_id=raw.get("parentTaxonId") or raw.get("parentId"),
        is_active=is_active,
        api_data=raw,
    )


def _flatten_hierarchy(node: Any, into: dict[int, TaxonData]) -> None:
    """Collect every named taxon from a ``/childhierarchy`` tree."""
    if isinstance(node, list):
        for item in node:
            _flatten_hierarchy(item, into)
        return
    if not isinstance(node, dict):
        return
    taxon_id = node.get("id") or node.get("taxonId")
    scientific = node.get("scientificName") or ""
    swedish = node.get("swedishName") or ""
    if taxon_id and (scientific or swedish) and int(taxon_id) not in into:
        into[int(taxon_id)] = TaxonData(
            dyntaxa_taxon_id=int(taxon_id),
            scientific_name=scientific,
            swedish_name=swedish,
            taxon_rank=str(node.get("taxonCategoryId") or ""),
            parent_dyntaxa_taxon_id=None,
            is_active=bool(node.get("isAccepted", True)),
            api_data=node,
        )
    _flatten_hierarchy(node.get("children"), into)


def category_taxa(under_taxon_id: int) -> list[TaxonData]:
    """Every taxon at or below ``under_taxon_id``, names included — one
    ``GET /taxa/{id}/childhierarchy`` call.
    """
    if under_taxon_id <= 0:
        raise ValueError("under_taxon_id must be a positive integer")
    payload = _call(
        "GET", "TAXON_SERVICE_URL", "SUBSCRIPTION_KEY_TAXON",
        f"/taxa/{under_taxon_id}/childhierarchy",
        params={"levels": TAXON_SUBTREE_LEVELS, "onlyMainChildren": "true"},
    )
    collected: dict[int, TaxonData] = {}
    _flatten_hierarchy(payload, collected)
    return list(collected.values())


def _match_score(taxon: TaxonData, needle: str) -> tuple[int, str] | None:
    """Rank key for a taxon against a case-folded query, or ``None`` if no match."""
    names = [taxon["scientific_name"].casefold(), taxon.get("swedish_name", "").casefold()]
    if any(name == needle for name in names):
        rank = 0
    elif any(name.startswith(needle) for name in names):
        rank = 1
    elif any(needle in name for name in names):
        rank = 2
    else:
        return None
    return rank, taxon.get("swedish_name") or taxon["scientific_name"]


def _is_species(taxon: TaxonData) -> bool:
    """True when a normalized taxon sits at species rank (Dyntaxa category 17).

    Excludes ranks above (genus, family, ...) and below (subspecies, variety).
    """
    raw = taxon.get("api_data") or {}
    category = raw.get("category")
    if isinstance(category, dict) and (
        category.get("id") == TAXON_CATEGORY_SPECIES
        or category.get("value") == "Species"
    ):
        return True
    if raw.get("taxonCategoryId") == TAXON_CATEGORY_SPECIES:
        return True
    return str(taxon.get("taxon_rank", "")).strip().lower() in {"species", "art"}


def search_taxa(
    query: str,
    *,
    under_taxon_id: int | None = None,
    limit: int = TAXON_SEARCH_DEFAULT_LIMIT,
) -> list[TaxonData]:
    """Find *species* whose Swedish or scientific name matches ``query``.

    Only species-rank taxa are returned; higher ranks and subspecies are
    filtered out.

    With ``under_taxon_id`` (a ``SpeciesCategory.taxon_id``): the search runs
    against that category's cached taxon subtree only — **one** API call the first
    time the category is searched, then zero. Nothing outside the branch is ever
    considered.

    Without it: one ``GET /taxa/search`` call against all of Dyntaxa.
    """
    if not query.strip():
        return []
    limit = max(1, min(limit, TAXON_SEARCH_MAX_LIMIT))
    needle = query.strip().casefold()

    if under_taxon_id:
        scored = []
        for taxon in category_taxa(under_taxon_id):
            score = _match_score(taxon, needle)
            if score is not None and _is_species(taxon):
                scored.append((score, taxon))
        scored.sort(key=lambda pair: pair[0])
        return [taxon for _, taxon in scored[:limit]]

    payload = _call(
        "GET", "TAXON_SERVICE_URL", "SUBSCRIPTION_KEY_TAXON", "/taxa/search",
        params={
            "searchString": query,
            "searchFields": "Both",
            "culture": "sv_SE",
            "isOkForObservationSystems": "True",
            "page": 1,
            "pageSize": max(limit * 3, 60),
        },
    )
    hits = payload if isinstance(payload, list) else (
        payload.get("data") or payload.get("records") or payload.get("taxa") or []
    )
    results: dict[int, TaxonData] = {}
    for hit in hits:
        if not isinstance(hit, dict) or not (
            hit.get("taxonId") or (hit.get("taxonInformation") or {}).get("taxonId")
        ):
            continue
        taxon = _normalize_taxon(hit)
        if not _is_species(taxon):
            continue
        if taxon["dyntaxa_taxon_id"] not in results:
            results[taxon["dyntaxa_taxon_id"]] = taxon
        if len(results) >= limit:
            break
    return list(results.values())


def get_taxon(taxon_id: int) -> TaxonData:
    """Fetch and normalize one Dyntaxa taxon.

    Detail is ``POST /taxa`` with a body of ids (there is no ``GET /taxa/{id}``).
    """
    if taxon_id <= 0:
        raise ValueError("taxon_id must be a positive integer")
    payload = _call(
        "POST", "TAXON_SERVICE_URL", "SUBSCRIPTION_KEY_TAXON", "/taxa",
        params={"culture": "sv_SE"},
        json={"taxonIds": [taxon_id]},
    )
    hits = payload if isinstance(payload, list) else (
        payload.get("data") or payload.get("records") or payload.get("taxa") or []
    )
    if not hits:
        raise ArtdatabankenAPIError(
            "POST", "/taxa", 404, f"Dyntaxa taxon {taxon_id} not found"
        )
    return _normalize_taxon(hits[0])


def get_species_information(taxon_id: int) -> dict[str, Any]:
    """Fetch Artfakta species information for a Dyntaxa taxon ID."""
    if taxon_id <= 0:
        raise ValueError("taxon_id must be a positive integer")
    return _call(
        "GET", "SPECIES_INFORMATION_URL", "SUBSCRIPTION_KEY_SPECIES_INFORMATION",
        f"/species/{taxon_id}",
    )


# Artfakta significance labels -> stored two-level code ("stor" > "har").
# The landskapstyper dataset uses the "betydelse" wording; biotoper uses
# "Viktig" / "Utnyttjas". Both are folded onto the same scale; anything not
# listed here (incl. null / "Ingen") is treated as no significance and dropped.
_SPECIESDATA_SIGNIFICANCE = {
    "Stor betydelse": "stor",
    "Har betydelse": "har",
    "Viktig": "stor",
    "Utnyttjas": "har",
}
# Backwards-compatible alias.
_LANDSCAPE_SIGNIFICANCE = _SPECIESDATA_SIGNIFICANCE

# Artfakta SpeciesDataService dataset path segments. ``landscapetypes`` is
# confirmed working; the biotoper segment is *not* verified against the Artfakta
# OpenAPI - if biotopes stay empty, a 404 here is the likely cause. Candidates
# seen in the wild: "biotopes", "biotopetypes", "habitats". Override without a
# code change via settings.ARTDATABANKEN["SPECIESDATA_BIOTOPES_PATH"].
LANDSCAPES_DATASET = "landscapetypes"
BIOTOPES_DATASET = "biotopes"


def _species_dataset(taxon_id: int, dataset: str) -> Any:
    """One Artfakta SpeciesDataService dataset for a Dyntaxa taxon ID.

    ``GET {SPECIES_INFORMATION_URL}/speciesdataservice/v1/speciesdata/<dataset>?taxa=<id>``
    -> ``[{"speciesData": [{"id", "name", "status"}], "taxonId": ...}]``.
    """
    if taxon_id <= 0:
        raise ValueError("taxon_id must be a positive integer")
    return _call(
        "GET", "SPECIES_INFORMATION_URL", "SUBSCRIPTION_KEY_SPECIES_INFORMATION",
        f"/speciesdataservice/v1/speciesdata/{dataset}",
        params={"taxa": taxon_id},
    )


def get_species_landscapes(taxon_id: int) -> Any:
    """Fetch the Artfakta *landskapstyper* block for a Dyntaxa taxon ID."""
    return _species_dataset(
        taxon_id, _config().get("SPECIESDATA_LANDSCAPES_PATH", LANDSCAPES_DATASET)
    )


def get_species_biotopes(taxon_id: int) -> Any:
    """Fetch the Artfakta *biotoper* block for a Dyntaxa taxon ID.

    The dataset path segment is unverified - see :data:`BIOTOPES_DATASET`.
    """
    return _species_dataset(
        taxon_id, _config().get("SPECIESDATA_BIOTOPES_PATH", BIOTOPES_DATASET)
    )


# Keys the SpeciesDataService rows have used for the taxon id and the entry list.
_SPECIESDATA_TAXON_KEYS = ("taxonId", "taxonid", "dyntaxaTaxonId", "taxon")
_SPECIESDATA_ENTRY_KEYS = ("speciesData", "speciesdata", "data", "values", "items")
_SPECIESDATA_NAME_KEYS = ("name", "title", "label", "text")
_SPECIESDATA_STATUS_KEYS = ("status", "significance", "importance", "value")


def _first(mapping: dict, keys, default=None):
    for key in keys:
        if mapping.get(key) not in (None, ""):
            return mapping[key]
    return default


def _normalize_speciesdata(
    payload: Any, taxon_id: int | None = None, *, label: str = "speciesdata"
) -> list[dict]:
    """``[{speciesData: [{id, parentId, name, significance}], taxonId}]`` ->
    ``[{id, parent_id, code, name, significance}]``.

    Shared shape for the *landskapstyper* and *biotoper* datasets. Keeps only
    rows whose significance is in :data:`_SPECIESDATA_SIGNIFICANCE` (folded to
    ``stor`` / ``har``); ``null`` / ``"Ingen"`` are dropped. ``code`` is parsed
    from a trailing ``(X)`` in ``name`` when present (rare), else ``""``.
    Tolerant of key-name drift; logs when a non-empty payload yields nothing.
    """
    rows = payload if isinstance(payload, list) else [payload] if payload else []
    out: list[dict] = []
    seen_entries = 0
    seen_statuses: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_taxon = _first(row, _SPECIESDATA_TAXON_KEYS)
        if taxon_id is not None and row_taxon is not None and row_taxon != taxon_id:
            continue
        entries = _first(row, _SPECIESDATA_ENTRY_KEYS) or []
        if not isinstance(entries, list):
            entries = [entries]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            seen_entries += 1
            status = str(_first(entry, _SPECIESDATA_STATUS_KEYS) or "").strip()
            seen_statuses.add(status)
            significance = _SPECIESDATA_SIGNIFICANCE.get(status)
            if not significance:
                continue
            raw_name = str(_first(entry, _SPECIESDATA_NAME_KEYS) or "").strip()
            code, name = "", raw_name
            if raw_name.endswith(")") and "(" in raw_name:
                cut = raw_name.rfind("(")
                code, name = raw_name[cut + 1:-1].strip(), raw_name[:cut].strip()
            out.append({
                "id": entry.get("id") or entry.get("Id"),
                "parent_id": entry.get("parentId") or entry.get("parent_id"),
                "code": code,
                "name": name,
                "significance": significance,
            })
    if rows and not out:
        logger.warning(
            "%s: %d row(s), %d entr(y/ies), no significant rows kept. "
            "Statuses seen: %s. Top-level keys: %s",
            label, len(rows), seen_entries, sorted(seen_statuses) or "none",
            sorted(rows[0].keys()) if isinstance(rows[0], dict) else type(rows[0]).__name__,
        )
    return out


# Backwards-compatible alias.
_normalize_landscapes = _normalize_speciesdata


@transaction.atomic
def upsert_species(taxon_id: int) -> Species:
    """Create or refresh the local Species cache from Dyntaxa and Artfakta.

    Dyntaxa taxonomy is required. Artfakta data - species information,
    *landskapstyper* (``landscape_types``) and *biotoper* (``biotopes``) - is
    best-effort (a separate, optional subscription); any piece that fails is
    skipped and its previously stored value kept. This is also the resync path:
    it is ``update_or_create`` on ``dyntaxa_taxon_id``.
    """
    taxon = get_taxon(taxon_id)
    raw_data = dict(taxon["api_data"])
    try:
        raw_data["species_information"] = get_species_information(taxon_id)
    except (ArtdatabankenConfigurationError, ArtdatabankenAPIError):
        raw_data["species_information"] = None

    defaults = {
        "scientific_name": taxon["scientific_name"],
        "swedish_name": taxon.get("swedish_name", ""),
        "taxon_rank": taxon.get("taxon_rank", ""),
        "parent_dyntaxa_taxon_id": taxon.get("parent_dyntaxa_taxon_id"),
        "is_active": taxon.get("is_active", True),
        "api_data": raw_data,
        "synced_at": timezone.now(),
    }
    for field, fetch in (
        ("landscape_types", get_species_landscapes),
        ("biotopes", get_species_biotopes),
    ):
        try:
            defaults[field] = _normalize_speciesdata(
                fetch(taxon_id), taxon_id, label=f"upsert_species({taxon_id}).{field}"
            )
        except ArtdatabankenConfigurationError:
            pass  # no Artfakta key configured; keep any stored value
        except ArtdatabankenAPIError as exc:
            # Keep the stored value, but make the failure visible - a 404 here
            # usually means the dataset path segment is wrong (see BIOTOPES_DATASET).
            logger.warning(
                "upsert_species(%s): %s fetch failed, keeping stored value: %s",
                taxon_id, field, exc,
            )

    species, _ = Species.objects.update_or_create(
        dyntaxa_taxon_id=taxon["dyntaxa_taxon_id"], defaults=defaults
    )
    return species


@transaction.atomic
def register_species(
    *, category: SpeciesCategory, dyntaxa_taxon_id: int
) -> Species:
    """Fetch a taxon from the Artdatabanken APIs and file it under ``category``.

    Pulls taxonomy (Dyntaxa) and species information (Artfakta) for
    ``dyntaxa_taxon_id``, caches it as a local :class:`Species`, and adds it to
    ``category.species`` (idempotent).
    """
    species = upsert_species(dyntaxa_taxon_id)
    category.species.add(species)  # idempotent
    return species


# Default staleness threshold for a bulk resync (mirrors the management command).
RESYNC_STALE_AFTER_DAYS = 30


def stale_species(*, older_than_days: int = RESYNC_STALE_AFTER_DAYS, queryset=None):
    """Species due a resync: never synced, or ``synced_at`` older than the cutoff."""
    base = Species.objects.all() if queryset is None else queryset
    cutoff = timezone.now() - datetime.timedelta(days=max(0, older_than_days))
    return (
        base.filter(synced_at__isnull=True) | base.filter(synced_at__lt=cutoff)
    ).order_by("scientific_name")


def resync_species_batch(species_iter) -> Iterator[tuple[int, Species | None, "ArtdatabankenAPIError | None"]]:
    """Refresh each Species from ``species_iter``, one atomic upsert at a time.

    Yields ``(dyntaxa_taxon_id, refreshed_species_or_None, api_error_or_None)``
    so callers can stream progress. An :class:`ArtdatabankenAPIError` on one
    species is reported and the loop continues;
    :class:`ArtdatabankenConfigurationError` propagates - it would fail for
    every row.
    """
    for species in species_iter:
        taxon_id = species.dyntaxa_taxon_id
        try:
            yield taxon_id, upsert_species(taxon_id), None
        except ArtdatabankenAPIError as exc:
            yield taxon_id, None, exc


# --------------------------------------------------------------------------- #
# Observations (Species Observation System)
# --------------------------------------------------------------------------- #
def search_observations(
    search_filter: dict, *, skip: int = 0, take: int = 100,
    sort_by: str | None = None, sort_order: str = "Asc",
) -> dict:
    """POST /Observations/Search. Returns ``{"totalCount": int, "records": [...]}``."""
    if take > SOS_MAX_TAKE:
        raise ValueError(f"take must be <= {SOS_MAX_TAKE}")
    if skip + take > SOS_MAX_WINDOW:
        raise ValueError(
            f"skip + take must be <= {SOS_MAX_WINDOW}; use an async export for bulk."
        )
    params: dict[str, Any] = {"skip": skip, "take": take}
    if sort_by:
        params["sortBy"] = sort_by
        params["sortOrder"] = sort_order
    return _call(
        "POST", "SPECIES_OBSERVATION_URL", "SUBSCRIPTION_KEY_SOS",
        "/Observations/Search", params=params, json=search_filter,
    )


def count_observations(search_filter: dict) -> int:
    """POST /Observations/Count."""
    result = _call(
        "POST", "SPECIES_OBSERVATION_URL", "SUBSCRIPTION_KEY_SOS",
        "/Observations/Count", json=search_filter,
    )
    if isinstance(result, dict):
        return int(result.get("count", result.get("totalCount", 0)))
    return int(result or 0)


def taxon_aggregation(search_filter: dict, *, skip: int = 0, take: int = 100) -> dict:
    """POST /Observations/TaxonAggregation - per-taxon observation counts."""
    return _call(
        "POST", "SPECIES_OBSERVATION_URL", "SUBSCRIPTION_KEY_SOS",
        "/Observations/TaxonAggregation", params={"skip": skip, "take": take},
        json=search_filter,
    )


def geo_grid_aggregation(search_filter: dict, *, zoom: int = 10) -> dict:
    """POST /Observations/GeoGridAggregation - bucket matching observations into
    a spatial grid. ``zoom`` sets the cell size (higher = finer). Returns
    ``{"gridCells": [{"boundingBox"|"bbox", "observationsCount", ...}]}`` (exact
    keys vary by API version; confirm against the SOS OpenAPI document).
    """
    return _call(
        "POST", "SPECIES_OBSERVATION_URL", "SUBSCRIPTION_KEY_SOS",
        "/Observations/GeoGridAggregation", params={"zoom": zoom},
        json=search_filter,
    )


def iter_observations(search_filter: dict, *, page_size: int = SOS_MAX_TAKE) -> Iterator[dict]:
    """Yield observation records, paging within the 10 000-record search window."""
    skip = 0
    while skip < SOS_MAX_WINDOW:
        take = min(page_size, SOS_MAX_WINDOW - skip)
        page = search_observations(search_filter, skip=skip, take=take)
        records = page.get("records") or []
        yield from records
        skip += take
        if not records or skip >= page.get("totalCount", 0):
            break
