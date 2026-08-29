# Species Observation System (SOS) — read API

Base: `https://api.artdatabanken.se/species-observation-system/v1`
Product: *Species Observations – multiple data resources*
Swagger/OpenAPI: download the OpenAPI 3 doc from the product page on the portal —
it is the authoritative schema. Interactive Swagger UI is linked from there.
Source / docs: <https://github.com/biodiversitydata-se/SOS>

> Aggregates 100M+ observations from most Swedish datasets, including Artportalen
> (dataProvider id `1`).

## Endpoints (most-used)

### Observations
| Method | Path | Purpose |
|---|---|---|
| POST | `/Observations/Search` | Observations matching a filter. Query: `?skip=&take=` (take ≤ 1000, skip+take ≤ 10000). |
| POST | `/Observations/SearchAggregatedInternal` / `/Observations/Count` | Count only. |
| GET | `/Observations/{occurrenceId}` | One observation by occurrenceId. |
| POST | `/Observations/GeoGridAggregation` | Bucket observations into a spatial grid. |
| POST | `/Observations/TaxonAggregation` | Counts grouped by taxon. |

### Exports (bulk, beyond the 10k cap)
| Method | Path | Purpose |
|---|---|---|
| POST | `/Exports/Download/Csv` \| `/GeoJson` \| `/Excel` \| `/DwC` | Sync download, ≤ 25 000 obs. |
| POST | `/Exports/Order/Csv` \| `/GeoJson` \| `/Excel` \| `/DwC` | Async order, ≤ 2M obs, emailed link. |
| GET | `/Exports/Datasets` | Available Darwin Core Archive datasets. |
| GET | `/Jobs/{jobId}/Status` | Poll an async order. |

### Reference data
| Method | Path | Purpose |
|---|---|---|
| GET | `/Areas` | Search areas (county, province, municipality, parish, …). |
| GET | `/Areas/{areaType}/{featureId}/Export` | Area polygon (zipped GeoJSON). |
| GET | `/DataProviders` | All datasets/providers + ids. |
| GET | `/Vocabularies` , `/Vocabularies/{id}` | Controlled vocabularies (activity, lifeStage, …). |
| GET | `/TaxonLists` , `/TaxonLists/{id}/Taxa` | Conservation lists mirrored into SOS. |
| GET | `/Locations/{id}` | Location detail. |
| GET | `/ApiInfo` | API metadata/version. |

## Search filter schema

`POST /Observations/Search` body. All top-level keys optional; combine freely
(AND semantics). Confirm exact names/enums against the OpenAPI doc.

```jsonc
{
  "taxon": {
    "ids": [4000107],                 // Dyntaxa taxon IDs
    "includeUnderlyingTaxa": true,    // include children (e.g. genus -> species)
    "taxonListIds": [1],              // restrict to a conservation list
    "redListCategories": ["CR","EN","VU"]
  },
  "date": {
    "startDate": "2024-01-01",
    "endDate": "2024-12-31",
    "dateFilterType": "OverlappingStartDateAndEndDate",
      // OnlyStartDate | OnlyEndDate | OverlappingStartDateAndEndDate | BetweenStartDateAndEndDate
    "timeRanges": ["Morning"]         // optional
  },
  "geographics": {
    "areas": [{ "areaType": "County", "featureId": "1" }],
      // areaType: Country|County|Province|Municipality|Parish|CountryRegion|
      //           BirdValidationArea|Sea|WaterArea|ProtectedNature
    "geometries": [ { "type": "Polygon", "coordinates": [[[/* lon,lat */]]] } ],
    "maxDistanceFromPoint": 500,      // metres, with a Point geometry
    "considerObservationAccuracy": true
  },
  "dataProvider":  { "ids": [1] },     // 1 = Artportalen; see GET /DataProviders
  "dataset":       { "ids": [] },
  "occurrenceStatus": "Present",       // Present | Absent | BothPresentAndAbsent
  "notRecoveredFilter": "NoFilter",
  "birdNestActivityLimit": 0,
  "modifiedDate": { "from": "2024-06-01T00:00:00Z", "to": null },
  "validationStatus": "Any",
  "verificationStatus": "Verified",    // BothVerifiedAndNotVerified | Verified | NotVerified
  "onlyWithMedia": false,
  "projectIds": [],
  "output": {
    "fields": [
      "occurrence.occurrenceId",
      "occurrence.occurrenceStatus",
      "taxon.id",
      "taxon.scientificName",
      "taxon.vernacularName",
      "event.startDate",
      "event.endDate",
      "location.decimalLatitude",
      "location.decimalLongitude",
      "location.county",
      "location.municipality"
    ]
  }
}
```

Notes:
- **Field sets:** instead of `output.fields`, some deployments accept
  `?outputFieldSet=Minimum|Extended|AllWithValues|AllWithId`. Prefer an explicit
  `output.fields` list to keep payloads small.
- **Response:** `{ "totalCount": n, "records": [ ... ] }` for Search;
  `{ "count": n }` for Count.
- **Coordinates** default to WGS84 decimal degrees; request other systems with
  `?coordinateSystem=` if supported. Sensitive taxa are returned with
  **diffused/generalized** coordinates unless you send an OAuth token with
  `SOS.Observations.Protected`.
- **Sorting:** `?sortBy=event.startDate&sortOrder=Desc`.
- **Translations:** `?translationCultureCode=sv-SE` for vernacular names/enum
  labels.

## Limits

- Search: hard cap 10 000 records total (`skip + take`), 1 000 per page → HTTP
  error if exceeded.
- Sync export: 25 000. Async order: 2 000 000 (emailed).
- Use `TaxonAggregation` / `GeoGridAggregation` when you only need counts.
