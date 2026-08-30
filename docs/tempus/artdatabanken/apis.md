# API products and implemented functions

All external calls belong in `tempus/services/artdatabanken.py`; views and
tasks should not call Artdatabanken directly.

## Dyntaxa Taxon Service

Default base: `https://api.artdatabanken.se/taxonservice/v1`

| Tempus function | External operation | Purpose |
|---|---|---|
| `search_taxa()` | `/taxa/search` or cached hierarchy | Scientific/Swedish species search |
| `category_taxa()` | `/taxa/{id}/childhierarchy` | Resolve a category subtree |
| `get_taxa()` | `POST /taxa` | Fetch and normalize several IDs |
| `get_taxon()` | `POST /taxa` | Fetch one ID through the batch endpoint |
| `upsert_species()` | Dyntaxa + optional Artfakta | Create or refresh local cache |
| `register_species()` | Local transaction | Add cached species to category |
| `stale_species()` | Local query | Select rows due for refresh |
| `resync_species_batch()` | Repeated upsert | Refresh independently and report failures |

Only species-rank search results are returned. Category subtrees are cached for
24 hours. Response normalization is defensive because Dyntaxa endpoints differ;
the current product OpenAPI specification is authoritative.

## Artfakta Species Information

Default base: `https://api.artdatabanken.se/information/v1`

Implemented: general species information, landscape types, and biotopes.
Significance is normalized to `stor` (“Stor betydelse”/“Viktig”) or `har`
(“Har betydelse”/“Utnyttjas”); rows without significance are omitted.

Artfakta is best-effort during upsert. Failures do not block taxonomy and old
landscape/biotope data is retained. The default `biotopes` dataset path is not
verified for every deployment and can be overridden through configuration.

## Species Observation System

Default base:
`https://api.artdatabanken.se/species-observation-system/v1`

| Function | Endpoint | Purpose |
|---|---|---|
| `search_observations()` | `POST /Observations/Search` | Paged search |
| `iter_observations()` | repeated Search | Iterate within search window |
| `count_observations()` | `POST /Observations/Count` | Count matches |
| `taxon_aggregation()` | `POST /Observations/TaxonAggregation` | Group by taxon |
| `geo_grid_aggregation()` | `POST /Observations/GeoGridAggregation` | Occupied spatial cells |

Search is limited to 1,000 rows per page and a 10,000-row paging window, both
enforced locally. Bulk export is not currently implemented. Common filters are
`taxon`, `date`, `geographics`, `dataProvider`, `occurrenceStatus`, and
`output`. Provider ID 1 currently represents Artportalen, but reference data
should be consulted rather than treating that as an eternal constant.

## Taxon List Service

Red-list and conservation lists are not directly integrated. SOS mirrors these
lists and supports observation filtering by list IDs and red-list categories.

## Errors

Missing configuration raises `ArtdatabankenConfigurationError`. Non-success
HTTP responses raise `ArtdatabankenAPIError`. Batch resync reports individual
API failures and continues; callers should handle errors at request/task edges.

