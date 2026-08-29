# Taxonomy — Dyntaxa Taxon Service + Taxon List Service

Both are fully open (subscription key only). One key covers both under the
*Taxonomy* product family. Download each product's OpenAPI 3 doc from the portal
for exact paths/params — the paths below match the public v1 docs but SLU has
revised them between minor versions.

## Dyntaxa Taxon Service

Base: `https://api.artdatabanken.se/taxonservice/v1`

> Swedish organism taxonomy from Dyntaxa. Taxon IDs here ("dyntaxa taxon id")
> are the same IDs the SOS `taxon.ids` filter expects.

| Method | Path | Purpose |
|---|---|---|
| GET | `/taxa/{taxonId}` | Taxon detail: scientific + recommended names (multi-language), category, taxonomic status, valid/invalid. |
| GET | `/taxa/names?searchString={q}&...` | Name search — scientific or Swedish name → matching taxa. Params typically include `culture`, `searchFields`, `isRecommended`, `page`, `pageSize`. Use this to resolve a name to a taxon ID. |
| GET | `/taxa/{taxonId}/parents` | Ancestor chain to root. |
| GET | `/taxa/{taxonId}/children` | Direct children. |
| GET | `/taxa/{taxonId}/synonyms` | Synonyms / non-recommended names. |
| GET | `/taxa?changedSince={date}&taxonCategoryIds=&taxonGroupIds=` | Filtered list of taxon IDs (e.g. everything added/changed since a date). |
| GET | `/darwincorearchive` (or `/darwincore/download`) | Full Dyntaxa as a Darwin Core Archive, rebuilt daily. `?format=gbif` or Dyntaxa-native. |

Response shape for a taxon (abridged):

```jsonc
{
  "taxonId": 102822,
  "scientificName": "Bombus lucorum",
  "author": "(Linnaeus, 1761)",
  "recommendedNames": [
    { "name": "ljus jordhumla", "culture": "sv-SE", "isRecommended": true },
    { "name": "Bombus lucorum", "culture": "lat", "isRecommended": true }
  ],
  "category": { "id": 17, "name": "Art" },      // Art = species
  "taxonomicStatus": "accepted",
  "isValid": true,
  "parentTaxonId": 102821
}
```

### Name → ID matching guidance

- Prefer exact match on `scientificName`; fall back to Swedish vernacular via
  `culture=sv-SE`.
- A query can return multiple hits (homonyms, synonyms pointing at different
  accepted taxa). Surface ambiguity rather than silently taking the first.
- Cache the mapping. Dyntaxa changes slowly; a nightly refresh is plenty.
- Keep the accepted `taxonId`; if a name resolves to a synonym, follow it to the
  accepted taxon before using it in SOS filters.

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
