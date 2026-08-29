# Taxonomy — Dyntaxa Taxon Service + Taxon List Service

Both are fully open (subscription key only). One key covers both under the
*Taxonomy* product family.

## Dyntaxa Taxon Service

Base: `https://api.artdatabanken.se/taxonservice/v1`
Portal: <https://api-portal.artdatabanken.se/api-details#api=taxonservice> —
"API definition → Open API 3 (JSON)" is the authoritative schema.

> Swedish organism taxonomy from Dyntaxa. Taxon IDs here ("dyntaxa taxon id")
> are the same IDs the SOS `taxon.ids` filter expects.

**Every operation** (from the OpenAPI, `taxonservice/v1`, checked 2026-08):

| operationId | Method | Path | Purpose |
|---|---|---|---|
| `Taxon_GetTaxa` | **POST** | `/taxa?culture=sv_SE` | **Taxon detail — batch.** Body `{"taxonIds":[int,…]}`, `Content-Type: application/json-patch+json`. Returns `TaxonDto[]`. **There is no `GET /taxa/{id}`.** |
| `Taxon_SearchTaxonNames` | GET | `/taxa/names` | Name search, **one row per matching name**. Returns `TaxonNameSearchResultDto[]`. |
| `Taxon_SearchBestMatchTaxa` | GET | `/taxa/search` | Name search, **one row per taxon**, ranked by match quality. Returns `{currentPage,totalNrOfPages,totalNrOfItems,data:TaxonSearchResultDto[]}`. Prefer this over `/taxa/names`. |
| `Taxon_GetParentIds` | GET | `/taxa/{id}/parentids` | **All** ancestor ids → `{"taxonIds":[0,…]}` (`0` = root, strip). |
| `Taxon_GetChildIds` | GET | `/taxa/{id}/childids?useMainChildren={bool}` | Child ids → `{"taxonIds":[…]}`. |
| `Taxon_GetTaxonChildrenHierarchy` | GET | `/taxa/{id}/childhierarchy?levels={int}&onlyMainChildren={bool}` | Nested descendant tree (`TaxonHierachyNodeModelDto`, key `id`, recurses under `children`). |
| `Taxon_GetFilteredSelectedTaxa` | GET | `/taxa/{id}/filteredSelected?taxonCategories={…}&createdDate=&modifiedDate=&onlyMainChildren={bool}` | Child hierarchy filtered by taxon category / change date. |
| `DarwinCore_DownloadDarwinCore` | GET | `/darwincore/…` | Full Dyntaxa as a Darwin Core Archive. |
| `Vocabulary_GetVocabulary`, `LinkedOpenData_GetData`, `DarwinCore_GetLastWriteTime` | GET | — | vocabularies / LOD / DwC timestamp. |

Shared query params for **both** name-search operations — nothing else:
`searchString`, `searchFields` (`Swedish`\|`Scientific`\|`Both`), `isRecommended`,
`isOkForObservationSystems`, `culture` (`sv_SE`\|`en_GB`), `page`, `pageSize`.

> Do **not** try `GET /taxa/{id}`, `/taxa/{id}/parents`, `/taxa/{id}/children`,
> `/taxa/{id}/synonyms`, or a `?taxonIds=` filter — none exist (404).

### Scoping a name search to a subtree (e.g. "birds only")

**Neither name-search operation takes a taxon / parent / category filter** — the
full param list is above, and it has none. Scope client-side. Two shapes:

- **Few hits, any-size scope** (autocomplete): search first, then for each of the
  ≤ N hits call `GET /taxa/{hitId}/parentids` and keep it iff `scopeId` is in the
  chain. Bounded by how many hits you show; each response is ~15 ints. Cache per
  taxon id. **This is what Tempus does.**
- **Small scope, many searches** (a curated category of a few hundred taxa):
  resolve the scope's descendant id set once via `childhierarchy` /
  `filteredSelected`, cache it, filter hits by membership. Do **not** do this for
  a broad node (`Insecta`, `Aves`) — the subtree is huge.

**`POST /taxa` (`TaxonDto`) and `GET /taxa/search` (`TaxonSearchResultDto`)** share
a shape — a flat `taxonId`, `parentId`, `category` (the *rank*: `value` =
`Species`, `name` = `Art`), `status`, and a `names[]` array where each entry's
**`category.value`** is the *name kind* (`ScientificName` / `SwedishName` / …):

```jsonc
{
  "taxonId": 102822,
  "parentId": 102821,
  "category": { "id": 17, "value": "Species", "name": "Art" },   // rank
  "status":   { "id": 0,  "value": "Accepted" },
  "names": [
    { "name": "Bombus lucorum", "nameShort": "lat", "isRecommended": true,
      "author": "(Linnaeus, 1761)", "category": { "value": "ScientificName" } },
    { "name": "ljus jordhumla",  "nameShort": "swe", "isRecommended": true,
      "category": { "value": "SwedishName" } }
  ]
}
```
`/taxa/search` wraps these in `{ currentPage, totalNrOfPages, totalNrOfItems,
data: [...] }` and adds `matchType` / `matchingNameId` per row.

**`GET /taxa/names` (`TaxonNameSearchResultDto`)** — `{ "data": [ … ], … }`, one
row **per name** (a taxon matching on both its scientific and Swedish name
appears twice). The row's own `id` is a **name id, not a taxon id**; the taxon
is nested under `taxonInformation`:

```jsonc
{
  "id": 46673,                       // name id — NOT the taxon id
  "name": "blå kärrhök",
  "nameShort": "swe",
  "category":  { "value": "Species", "name": "Art" },   // rank, confusingly
  "status":    { "value": "Accepted" },
  "parentId":  2002762,
  "taxonInformation": {
    "taxonId": 100034,               // <-- the Dyntaxa taxon id
    "recommendedScientificName": "Circus cyaneus",
    "recommendedSwedishName": "blå kärrhök"
  }
}
```

### Name → ID matching guidance

- Read the taxon id from `taxonInformation.taxonId`, the display names from
  `taxonInformation.recommendedScientificName` / `recommendedSwedishName` — never
  from the row's top-level `id` (name id) or `name` (the single matched name).
- De-duplicate on `taxonInformation.taxonId` — the same taxon recurs once per
  matching name.
- Prefer exact match on `recommendedScientificName`; fall back to the Swedish
  vernacular. Pass `isOkForObservationSystems=True` to drop names that Dyntaxa
  won't accept in reporting/observation contexts.
- A query can return multiple genuine hits (homonyms, synonyms pointing at
  different accepted taxa). Surface ambiguity rather than silently taking the first.
- Filter to `status.value == "Accepted"` to skip synonym rows.
- Cache the mapping. Dyntaxa changes slowly; a nightly refresh is plenty.

### Useful taxon categories (Dyntaxa `category.id`)

`Rike` kingdom · `Familj` family · `Släkte` genus · `Art` species ·
`Underart` subspecies · `Varietet` variety. Fetch the full list from the service
rather than hard-coding IDs.

## Taxon List Service

Base: `https://api.artdatabanken.se/taxonlistservice/v1`

> The Red List 2020 and other nature-conservation lists (invasive species,
> protected species, action-plan species, …).

| Method | Path | Purpose |
|---|---|---|
| GET | `/lists` | All available lists + ids + metadata. |
| GET | `/lists/{listId}` | List detail. |
| GET | `/lists/{listId}/taxa` | Taxa on the list, with per-taxon attributes (e.g. red list category `CR`/`EN`/`VU`/`NT`/`DD`). |

SOS also mirrors these — `GET /TaxonLists` on the SOS API and the
`taxon.taxonListIds` / `taxon.redListCategories` filter keys — so for
"observations of red-listed species in area X" you usually stay entirely within
SOS and never call this service directly.

## Artfakta – Species Information (optional)

Base: `https://api.artdatabanken.se/information/v1`

Species fact sheets: red list assessment text, ecology, conservation status,
substrate/habitat associations. Keyed by taxon ID. Only pull this in if Tempus
needs to *display* species facts, not for querying observations.
