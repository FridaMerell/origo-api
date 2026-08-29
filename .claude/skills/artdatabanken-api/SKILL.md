---
name: artdatabanken-api
description: >-
  Query and report species data through SLU Artdatabanken's APIs (Species
  Observation System, Dyntaxa taxonomy, Artfakta, and the Artportalen
  reporting/write API) for the Tempus project. Use this whenever the work
  touches Swedish species observations, taxon lookups, Dyntaxa taxon IDs, red
  list status, the Artportalen ("Artportalen") reporting flow, or anything under
  api.artdatabanken.se — including building a client, wiring auth
  (Ocp-Apim-Subscription-Key, OAuth against ids.artdatabanken.se), constructing
  observation search filters, resolving scientific/Swedish names to taxon IDs,
  or planning how to write observations back to Artportalen.
---

# Artdatabanken / Artportalen API integration

SLU Artdatabanken (Swedish Species Information Centre, part of SLU) exposes several
APIs behind one Azure API Management gateway at `https://api.artdatabanken.se`.
This skill covers using them from Tempus — a Python/Django project.

## The APIs, and which ones apply here

| Product (developer portal) | Base URL | Purpose | Access here |
|---|---|---|---|
| **Species Observations – multiple data resources** (SOS / "Species Observation System") | `https://api.artdatabanken.se/species-observation-system/v1` | Read observations from ~all Swedish datasets incl. Artportalen. Search, count, aggregate, export. | **Available** |
| **Dyntaxa Taxon Service** (Taxonomy) | `https://api.artdatabanken.se/taxonservice/v1` | Swedish taxonomy: taxon info, names ↔ taxon IDs, parents/children, synonyms, DwC-A export. | **Available** |
| **Taxon List Service** (Taxonomy) | `https://api.artdatabanken.se/taxonlistservice/v1` | Red List 2020 and other conservation lists. | **Available** |
| **Artfakta – Species Information** | `https://api.artdatabanken.se/information/v1` | Species facts: red list assessment, conservation, descriptions. | **Available** (optional) |
| **Artportalen – Species Observations Read and Write** | `https://api.artdatabanken.se/…` (assigned on grant) | Report (write) observations into Artportalen, plus Artportalen-specific reads. Part of *"API:er för särskild Artportalen-funktionalitet"*. | **NOT granted yet** — see below |

**Reporting observations back into Artportalen requires the Read+Write API, which
is not part of the products this account has.** It is "closed to new developers"
with occasional exceptions, and must be requested from SLU. Until then, treat
this skill's write side as *design + request path only*: build against the
sandbox if/when granted, do not assume it works. See
[references/artportalen-write.md](references/artportalen-write.md).

## Authentication

Two layers (details and code in [references/auth.md](references/auth.md)):

1. **Subscription key** — every request needs a header
   `Ocp-Apim-Subscription-Key: <key>`. Each *product* you subscribe to on
   [api-portal.artdatabanken.se](https://api-portal.artdatabanken.se/) has its
   own key (there is a primary and a secondary key per subscription). SOS and
   the taxonomy APIs are otherwise open — the key alone is enough for public
   data.

2. **OAuth 2.0 bearer token** — only needed for *protected* content: sensitive
   (redacted-location) observations via SOS, and everything in the Artportalen
   write API. Authorization Code + PKCE against `https://ids.artdatabanken.se`
   (older docs say `useradmin-auth.slu.se`; confirm the issuer in the portal).
   Header `Authorization: Bearer <token>`. SOS protected scope:
   `SOS.Observations.Protected`.

Store keys/secrets in environment variables, never in the repo:

```
ARTDATABANKEN_SOS_KEY=...
ARTDATABANKEN_TAXON_KEY=...
ARTDATABANKEN_ARTFAKTA_KEY=...        # optional
ARTPORTALEN_WRITE_KEY=...             # only once granted
ARTDATABANKEN_OAUTH_CLIENT_ID=...     # only for protected/write
ARTDATABANKEN_OAUTH_CLIENT_SECRET=...
```

In Django, read them via `os.environ` / `django-environ` in `settings.py` and
pass them into the client — don't have the client reach for Django settings
directly, so it stays reusable in scripts and tests.

## The bundled client

`scripts/artdatabanken_client.py` is a dependency-light (`requests` only) client.
Copy it into Tempus (e.g. `tempus/services/artdatabanken.py`) rather than
importing from the skill directory. It gives you:

- `ArtdatabankenClient(sos_key=..., taxon_key=..., ...)` — one object, one
  `requests.Session`, retries + timeout, raises `ArtdatabankenError` with the
  response body on non-2xx.
- **Observations:** `search_observations(filter, skip, take)`,
  `iter_observations(filter)` (auto-pages, respects the 10 000 hard cap),
  `count_observations(filter)`, `get_observation(occurrence_id)`,
  `taxon_aggregation(filter)`, `geo_grid_aggregation(filter)`.
- **Taxonomy:** `get_taxa([ids])` / `get_taxon(id)` (detail — `POST /taxa`, *not*
  `GET /taxa/{id}`), `search_taxa(name)` (`GET /taxa/search`, one row per taxon)
  / `find_taxa(name)` / `find_taxon_ids(name)` (`GET /taxa/names`, one row per
  name), `taxon_parent_ids(id)`, `taxon_child_ids(id)`,
  `taxon_child_hierarchy(id)` / `descendant_taxon_ids(id)`. **Neither name-search
  endpoint accepts a taxon/parent/category scope** — filter client-side (see
  `references/taxonomy.md`).
- **Reference data:** `data_providers()`, `vocabularies()`, `areas(...)`.
- **Write (stub):** `ArtportalenWriteClient` — documents the expected
  `report_sighting(...)` shape and raises a clear error explaining the access
  requirement until `ARTPORTALEN_WRITE_KEY` + OAuth are configured.

Exact request-body schemas for SOS search and some taxon-service paths are only
fully specified in the **OpenAPI 3 document you download from the portal** per
product. The client's shapes match the public documentation and the fields below;
if a call 400s, diff your body against that spec and adjust — then update the
client and [references/species-observations.md](references/species-observations.md).

## Common recipes

### Resolve a name to a Dyntaxa taxon ID, then search observations

```python
client = ArtdatabankenClient(sos_key=..., taxon_key=...)
ids = client.find_taxon_ids("Bombus lucorum")          # -> [1010931]
flt = {
    "taxon": {"ids": ids, "includeUnderlyingTaxa": True},
    "date": {"startDate": "2024-01-01", "endDate": "2024-12-31",
             "dateFilterType": "OverlappingStartDateAndEndDate"},
    "geographics": {"areas": [{"areaType": "County", "featureId": "1"}]},  # Stockholm
}
total = client.count_observations(flt)
for obs in client.iter_observations(flt):
    ...
```

### Filter building blocks (SOS `POST /Observations/Search`)

Full field list in [references/species-observations.md](references/species-observations.md). Most-used:

- `taxon`: `{ "ids": [int], "includeUnderlyingTaxa": bool }`
- `date`: `{ "startDate", "endDate", "dateFilterType" }` — type is one of
  `OnlyStartDate`, `OnlyEndDate`, `OverlappingStartDateAndEndDate`,
  `BetweenStartDateAndEndDate`.
- `geographics`: `{ "areas": [{areaType, featureId}], "geometries": [GeoJSON], "maxDistanceFromPoint": m }`
- `dataProvider`: `{ "ids": [int] }` (1 = Artportalen)
- `occurrenceStatus`: `"Present" | "Absent" | "BothPresentAndAbsent"`
- `output`: `{ "fields": ["occurrence.occurrenceId", "taxon.scientificName", ...] }` — trim the payload
- Paging is query params `?skip=&take=` (take ≤ 1000, skip+take ≤ 10 000).
  For more, use `POST /Exports/Order/*` (async, emailed) or the aggregation
  endpoints.

### Protected observations

Add an OAuth token with `SOS.Observations.Protected`; the client takes
`oauth_token_provider=<callable returning a fresh token>`. Without it you get
generalized coordinates for sensitive taxa. Never log or persist exact
coordinates of protected sightings.

## Building a "what's in season" feature

Phenology (species watchlist with a per-year "has it been reported?" check, and
a geographic "what to look for in area X" summary) is designed in
[references/seasonality.md](references/seasonality.md). The dependency-free
curve/scoring logic is in [scripts/phenology.py](scripts/phenology.py) — build
week-of-year phenograms, derive the activity window, score "coming into season".
Filter by adult stage with `activityIds` / `lifeStageIds` (imago, flowering) —
resolve the term id from `GET /Vocabularies`.

## Where to start

New to this? Read [references/examples.md](references/examples.md) — worked,
copy-adaptable code from "resolve a name" through to a full phenology feature,
with illustrative response shapes. Then run
`python scripts/demo_phenology.py` (no API key needed) to watch the seasonality
logic work on synthetic data.

## Tests

`tests/` holds stdlib-only unit tests for both bundled scripts:

```
cd <skill>/  &&  python -m unittest discover -s tests
```

`test_phenology.py` needs nothing installed; `test_client.py` stubs `requests`
if it's absent. Keep them green when you change the scripts, and copy the
relevant cases into Tempus's own suite when you port the code.

## Reference files

- [references/examples.md](references/examples.md) — **start here**: end-to-end worked examples.
- [references/auth.md](references/auth.md) — subscription keys, OAuth/PKCE flow, token caching, Django wiring.
- [references/species-observations.md](references/species-observations.md) — SOS endpoints, full filter schema, field sets, exports, aggregations, limits.
- [references/taxonomy.md](references/taxonomy.md) — Dyntaxa Taxon Service + Taxon List Service endpoints, name matching, taxon categories, DwC-A.
- [references/artportalen-write.md](references/artportalen-write.md) — how to request the Read+Write API, sandbox, OAuth, the reporting payload shape, and what to build now vs. after the grant.
- [references/seasonality.md](references/seasonality.md) — phenology engine: species watchlist + yearly reported-yet check, geographic "what to look for" summary, precompute schedule.

## Etiquette

- Set a descriptive `User-Agent` (e.g. `Tempus/1.0 (frida.merell@gmail.com)`).
- Cache taxonomy locally — it changes rarely; don't hit the taxon service per request.
- Respect the 10 000-record search cap; use exports for bulk.
- Watch the portal's API version history for breaking changes before upgrading `v1` → `v2`.
