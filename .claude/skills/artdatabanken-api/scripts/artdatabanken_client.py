"""Client for SLU Artdatabanken's APIs (SOS, Dyntaxa, Artfakta) + an Artportalen
write stub.

Dependency-light: only ``requests``. Copy this into Tempus (e.g.
``tempus/services/artdatabanken.py``) rather than importing it from the skill
directory, and adapt as the portal's OpenAPI docs dictate.

Design notes
------------
* One :class:`ArtdatabankenClient` holds one ``requests.Session`` with retries.
* Each product has its own subscription key; pass the ones you have.
* Protected observations and the write API need an OAuth bearer token. This
  client never runs the OAuth redirect flow itself -- pass
  ``oauth_token_provider``, a callable returning a currently-valid access token.
* Request-body schemas for SOS search / some taxon-service paths are only fully
  specified in the OpenAPI 3 doc you download per product from
  https://api-portal.artdatabanken.se/ . If a call returns 400, diff your body
  against that spec.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, Iterator, List, Optional

# ``requests`` is imported lazily in ArtdatabankenClient.__init__ so that the
# pure helpers (and the test suite) don't require it to be installed.

DEFAULT_BASE_URLS = {
    "sos": "https://api.artdatabanken.se/species-observation-system/v1",
    "taxon": "https://api.artdatabanken.se/taxonservice/v1",
    "taxonlist": "https://api.artdatabanken.se/taxonlistservice/v1",
    "artfakta": "https://api.artdatabanken.se/information/v1",
}

# SOS hard limits (see references/species-observations.md)
SOS_MAX_TAKE = 1000
SOS_MAX_WINDOW = 10_000

TokenProvider = Callable[[], str]


class ArtdatabankenError(RuntimeError):
    """Non-2xx response from an Artdatabanken API. Carries status + body."""

    def __init__(self, method: str, url: str, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"{method} {url} -> HTTP {status}: {body[:2000]}")


class ArtportalenAccessError(RuntimeError):
    """Raised when a write is attempted without the Read+Write API configured."""


class ArtdatabankenClient:
    def __init__(
        self,
        *,
        sos_key: Optional[str] = None,
        taxon_key: Optional[str] = None,
        artfakta_key: Optional[str] = None,
        oauth_token_provider: Optional[TokenProvider] = None,
        base_urls: Optional[Dict[str, str]] = None,
        user_agent: str = "Tempus/1.0 (+artdatabanken-api skill)",
        timeout: float = 30.0,
    ):
        self._keys = {
            "sos": sos_key,
            "taxon": taxon_key,
            "taxonlist": taxon_key,  # same Taxonomy product family
            "artfakta": artfakta_key,
        }
        self._base = {**DEFAULT_BASE_URLS, **(base_urls or {})}
        self._token_provider = oauth_token_provider
        self._timeout = timeout

        import requests
        from requests.adapters import HTTPAdapter

        self._session = requests.Session()
        self._session.headers["User-Agent"] = user_agent
        try:  # urllib3 v1/v2 compat
            from urllib3.util.retry import Retry

            retry = Retry(
                total=4,
                backoff_factor=0.5,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset({"GET", "POST"}),
                respect_retry_after_header=True,
            )
            self._session.mount("https://", HTTPAdapter(max_retries=retry))
        except ImportError:  # pragma: no cover
            pass

    # -- construction from env -------------------------------------------------
    @classmethod
    def from_env(cls, oauth_token_provider: Optional[TokenProvider] = None) -> "ArtdatabankenClient":
        return cls(
            sos_key=os.environ.get("ARTDATABANKEN_SOS_KEY"),
            taxon_key=os.environ.get("ARTDATABANKEN_TAXON_KEY"),
            artfakta_key=os.environ.get("ARTDATABANKEN_ARTFAKTA_KEY"),
            oauth_token_provider=oauth_token_provider,
        )

    # -- low-level request ---------------------------------------------------
    def _request(
        self,
        api: str,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        json: Any = None,
        protected: bool = False,
    ) -> Any:
        key = self._keys.get(api)
        if not key:
            raise ArtdatabankenError(
                method, path, 0,
                f"No subscription key configured for the '{api}' API.",
            )
        url = f"{self._base[api]}/{path.lstrip('/')}"
        headers = {"Ocp-Apim-Subscription-Key": key}
        if protected:
            if not self._token_provider:
                raise ArtdatabankenError(
                    method, url, 0,
                    "This call needs an OAuth bearer token; pass "
                    "oauth_token_provider to the client.",
                )
            headers["Authorization"] = f"Bearer {self._token_provider()}"

        resp = self._session.request(
            method, url, params=params, json=json,
            headers=headers, timeout=self._timeout,
        )
        if not resp.ok:
            raise ArtdatabankenError(method, url, resp.status_code, resp.text)
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    # ======================================================================
    # Species Observation System (SOS)
    # ======================================================================
    def search_observations(
        self,
        filter: dict,
        *,
        skip: int = 0,
        take: int = 100,
        sort_by: Optional[str] = None,
        sort_order: str = "Asc",
        translation_culture: str = "sv-SE",
        protected: bool = False,
        extra_params: Optional[dict] = None,
    ) -> dict:
        """POST /Observations/Search . Returns {"totalCount", "records"}."""
        if take > SOS_MAX_TAKE:
            raise ValueError(f"take must be <= {SOS_MAX_TAKE}")
        if skip + take > SOS_MAX_WINDOW:
            raise ValueError(
                f"skip+take must be <= {SOS_MAX_WINDOW}; use exports for bulk."
            )
        params = {
            "skip": skip,
            "take": take,
            "translationCultureCode": translation_culture,
        }
        if sort_by:
            params["sortBy"] = sort_by
            params["sortOrder"] = sort_order
        if extra_params:
            params.update(extra_params)
        return self._request(
            "sos", "POST", "/Observations/Search",
            params=params, json=filter, protected=protected,
        )

    def iter_observations(
        self, filter: dict, *, page_size: int = SOS_MAX_TAKE, protected: bool = False,
        **kwargs: Any,
    ) -> Iterator[dict]:
        """Yield observation records, auto-paging within the 10 000 window."""
        skip = 0
        while skip < SOS_MAX_WINDOW:
            take = min(page_size, SOS_MAX_WINDOW - skip)
            page = self.search_observations(
                filter, skip=skip, take=take, protected=protected, **kwargs
            )
            records = page.get("records") or []
            for rec in records:
                yield rec
            total = page.get("totalCount", 0)
            skip += take
            if skip >= total or not records:
                break

    def count_observations(self, filter: dict, *, protected: bool = False) -> int:
        res = self._request(
            "sos", "POST", "/Observations/Count", json=filter, protected=protected
        )
        if isinstance(res, dict):
            return res.get("count", res.get("totalCount", 0))
        return int(res)

    def get_observation(self, occurrence_id: str, *, protected: bool = False) -> dict:
        return self._request(
            "sos", "GET", f"/Observations/{occurrence_id}", protected=protected
        )

    def taxon_aggregation(
        self, filter: dict, *, skip: int = 0, take: int = 100, protected: bool = False
    ) -> dict:
        return self._request(
            "sos", "POST", "/Observations/TaxonAggregation",
            params={"skip": skip, "take": take}, json=filter, protected=protected,
        )

    def geo_grid_aggregation(
        self, filter: dict, *, zoom: int = 10, protected: bool = False
    ) -> dict:
        return self._request(
            "sos", "POST", "/Observations/GeoGridAggregation",
            params={"zoom": zoom}, json=filter, protected=protected,
        )

    def data_providers(self) -> List[dict]:
        return self._request("sos", "GET", "/DataProviders")

    def vocabularies(self) -> List[dict]:
        return self._request("sos", "GET", "/Vocabularies")

    def areas(
        self, *, area_types: Optional[List[str]] = None, search_string: Optional[str] = None,
        skip: int = 0, take: int = 100,
    ) -> dict:
        params: Dict[str, Any] = {"skip": skip, "take": take}
        if area_types:
            params["areaTypes"] = area_types
        if search_string:
            params["searchString"] = search_string
        return self._request("sos", "GET", "/Areas", params=params)

    def order_export(self, fmt: str, filter: dict, *, description: str = "") -> dict:
        """POST /Exports/Order/{fmt} -- async bulk export, emailed. fmt: Csv|GeoJson|Excel|DwC."""
        return self._request(
            "sos", "POST", f"/Exports/Order/{fmt}",
            params={"description": description}, json=filter, protected=True,
        )

    # ======================================================================
    # Dyntaxa Taxon Service
    # ======================================================================
    def get_taxa(self, taxon_ids: List[int], *, culture: str = "sv_SE") -> list:
        """POST /taxa -- taxon detail for one or more Dyntaxa taxon ids.

        There is no ``GET /taxa/{id}`` in this API; detail is a POST with a body
        of ids. Each returned item carries ``taxonId``, ``parentId`` /
        ``parentTaxonId``, ``category`` ``{value, name}`` and a ``names`` array
        of ``{name, nameShort, isRecommended, author, ...}`` (``nameShort`` is
        ``"lat"`` for the scientific name, ``"swe"`` for the Swedish name).
        """
        res = self._request(
            "taxon", "POST", "/taxa",
            params={"culture": culture},
            json={"taxonIds": [int(t) for t in taxon_ids]},
        )
        if isinstance(res, dict):
            return res.get("data") or res.get("records") or res.get("taxa") or []
        return res or []

    def get_taxon(self, taxon_id: int, *, culture: str = "sv_SE") -> Optional[dict]:
        """Convenience: taxon detail for a single id (``None`` if not found)."""
        hits = self.get_taxa([taxon_id], culture=culture)
        return hits[0] if hits else None

    def _name_search(
        self, path: str, name: str, *, culture: str, recommended_only: bool,
        ok_for_obs_only: bool, search_fields: str, page: int, page_size: int,
    ) -> list:
        res = self._request(
            "taxon", "GET", path,
            params={
                "searchString": name,
                "searchFields": search_fields,      # Swedish | Scientific | Both
                "culture": culture,                 # sv_SE | en_GB
                "isRecommended": "True" if recommended_only else "NotSet",
                "isOkForObservationSystems": "True" if ok_for_obs_only else "NotSet",
                "page": page,
                "pageSize": page_size,
            },
        )
        if isinstance(res, dict):
            return res.get("data") or res.get("records") or res.get("taxa") or []
        return res or []

    def find_taxa(
        self, name: str, *, culture: str = "sv_SE", recommended_only: bool = False,
        ok_for_obs_only: bool = False, search_fields: str = "Both",
        page: int = 1, page_size: int = 50,
    ) -> list:
        """GET /taxa/names -- name search -> matching *name* rows.

        One row per matching name (a taxon hit on both its scientific and Swedish
        name appears twice); the taxon is under ``taxonInformation``
        (``taxonId``, ``recommendedScientificName``, ``recommendedSwedishName``)
        and the row's own ``id`` is a *name* id. Neither this nor
        :meth:`search_taxa` accepts any taxon/parent/category scope — filter
        client-side with :meth:`taxon_parent_ids` or :meth:`descendant_taxon_ids`.
        """
        return self._name_search(
            "/taxa/names", name, culture=culture, recommended_only=recommended_only,
            ok_for_obs_only=ok_for_obs_only, search_fields=search_fields,
            page=page, page_size=page_size,
        )

    def search_taxa(
        self, name: str, *, culture: str = "sv_SE", recommended_only: bool = False,
        ok_for_obs_only: bool = False, search_fields: str = "Both",
        page: int = 1, page_size: int = 50,
    ) -> list:
        """GET /taxa/search -- best-match name search, **one row per taxon**.

        Ranked by match quality; each row has a flat ``taxonId``, ``parentId``,
        ``category`` (rank) and a ``names`` array. Usually nicer than
        :meth:`find_taxa` (no per-name duplicates).
        """
        return self._name_search(
            "/taxa/search", name, culture=culture, recommended_only=recommended_only,
            ok_for_obs_only=ok_for_obs_only, search_fields=search_fields,
            page=page, page_size=page_size,
        )

    @staticmethod
    def _hit_taxon_id(hit: dict) -> Optional[int]:
        info = hit.get("taxonInformation") or {}
        tid = info.get("taxonId") or hit.get("taxonId") or hit.get("acceptedTaxonId")
        return int(tid) if tid is not None else None

    def find_taxon_ids(self, name: str, **kwargs: Any) -> List[int]:
        """Convenience: names search -> list of unique taxon IDs (ints)."""
        ids: List[int] = []
        for hit in self.find_taxa(name, **kwargs):
            tid = self._hit_taxon_id(hit)
            if tid is not None and tid not in ids:
                ids.append(tid)
        return ids

    def taxon_parent_ids(self, taxon_id: int) -> List[int]:
        """GET /taxa/{id}/parentids -- ancestor taxon ids, root first.

        Response is ``{"taxonIds": [0, ...]}``; ``0`` is the tree root and is
        stripped here.
        """
        res = self._request("taxon", "GET", f"/taxa/{taxon_id}/parentids")
        return [int(i) for i in (res or {}).get("taxonIds", []) if i]

    def taxon_child_ids(self, taxon_id: int, *, main_only: bool = True) -> List[int]:
        """GET /taxa/{id}/childids -- direct child taxon ids (one level only)."""
        res = self._request(
            "taxon", "GET", f"/taxa/{taxon_id}/childids",
            params={"useMainChildren": str(main_only).lower()},
        )
        return [int(i) for i in (res or {}).get("taxonIds", []) if i]

    def taxon_child_hierarchy(
        self, taxon_id: int, *, levels: int = 100, main_only: bool = True,
    ) -> Any:
        """GET /taxa/{id}/childhierarchy -- the recursive descendant subtree."""
        return self._request(
            "taxon", "GET", f"/taxa/{taxon_id}/childhierarchy",
            params={"levels": levels, "onlyMainChildren": str(main_only).lower()},
        )

    def descendant_taxon_ids(
        self, taxon_id: int, *, include_self: bool = True, main_only: bool = True,
    ) -> List[int]:
        """Flatten ``childhierarchy`` to the set of taxon ids under ``taxon_id``.

        Use this once per scope node and cache it to filter name-search hits to a
        subtree (``/taxa/names`` has no server-side taxon scoping).
        """
        tree = self.taxon_child_hierarchy(taxon_id, main_only=main_only)
        out: List[int] = [int(taxon_id)] if include_self else []

        def _walk(node: Any) -> None:
            if isinstance(node, dict):
                tid = node.get("taxonId") or node.get("id")
                if tid is not None and int(tid) not in out:
                    out.append(int(tid))
                for key in ("children", "childTaxa", "childHierarchy", "nodes"):
                    _walk(node.get(key))
            elif isinstance(node, list):
                for item in node:
                    _walk(item)

        _walk(tree)
        return out

    # ======================================================================
    # Taxon List Service (Red List etc.)
    # ======================================================================
    def taxon_lists(self) -> list:
        return self._request("taxonlist", "GET", "/lists")

    def taxon_list_taxa(self, list_id: int) -> list:
        return self._request("taxonlist", "GET", f"/lists/{list_id}/taxa")

    # ======================================================================
    # Artfakta (optional)
    # ======================================================================
    def species_information(self, taxon_id: int) -> dict:
        return self._request("artfakta", "GET", f"/species/{taxon_id}")


class ArtportalenWriteClient:
    """Stub for the Artportalen 'Species Observations Read and Write' API.

    That product is NOT part of this account's subscriptions (it sits under
    "API:er för särskild Artportalen-funktionalitet", closed to new developers).
    See references/artportalen-write.md for how to request access + the sandbox.

    Once granted, fill in the HTTP calls against the product's OpenAPI 3 doc.
    Keep the method signatures so callers don't change.
    """

    def __init__(
        self,
        *,
        write_key: Optional[str] = None,
        base_url: Optional[str] = None,
        oauth_token_provider: Optional[TokenProvider] = None,
        user_agent: str = "Tempus/1.0 (+artdatabanken-api skill)",
        timeout: float = 30.0,
    ):
        self._key = write_key or os.environ.get("ARTPORTALEN_WRITE_KEY")
        self._base = base_url or os.environ.get("ARTPORTALEN_WRITE_BASE_URL")
        self._token_provider = oauth_token_provider
        self._user_agent = user_agent
        self._timeout = timeout
        import requests

        self._session = requests.Session()
        self._session.headers["User-Agent"] = user_agent

    @property
    def is_configured(self) -> bool:
        return bool(self._key and self._base and self._token_provider)

    def _guard(self) -> None:
        if not self.is_configured:
            raise ArtportalenAccessError(
                "Artportalen write API is not configured. Needs ARTPORTALEN_WRITE_KEY, "
                "a base URL, and an OAuth token provider. This account is not yet "
                "subscribed to the Read+Write product -- see "
                "references/artportalen-write.md."
            )

    def _headers(self) -> dict:
        return {
            "Ocp-Apim-Subscription-Key": self._key,
            "Authorization": f"Bearer {self._token_provider()}",  # type: ignore[misc]
        }

    def report_sighting(self, sighting: dict) -> dict:
        """Create one observation in Artportalen. Payload shape:
        references/artportalen-write.md. Verify path/version on grant."""
        self._guard()
        resp = self._session.post(
            f"{self._base}/sightings", json=sighting,
            headers=self._headers(), timeout=self._timeout,
        )
        if not resp.ok:
            raise ArtdatabankenError("POST", resp.url, resp.status_code, resp.text)
        return resp.json()

    def update_sighting(self, sighting_id: int, patch: dict) -> dict:
        self._guard()
        resp = self._session.put(
            f"{self._base}/sightings/{sighting_id}", json=patch,
            headers=self._headers(), timeout=self._timeout,
        )
        if not resp.ok:
            raise ArtdatabankenError("PUT", resp.url, resp.status_code, resp.text)
        return resp.json()

    def delete_sighting(self, sighting_id: int) -> None:
        self._guard()
        resp = self._session.delete(
            f"{self._base}/sightings/{sighting_id}",
            headers=self._headers(), timeout=self._timeout,
        )
        if not resp.ok:
            raise ArtdatabankenError("DELETE", resp.url, resp.status_code, resp.text)


if __name__ == "__main__":  # tiny smoke test
    c = ArtdatabankenClient.from_env()
    print("data providers:", len(c.data_providers()))
    print("Bombus lucorum ->", c.find_taxon_ids("Bombus lucorum"))
