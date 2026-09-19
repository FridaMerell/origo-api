# OpenStreetMap: buildings (Overpass)

Building footprints for a Locale come from **OpenStreetMap**, queried through
the public Overpass API. They replace Lantmäteriet's Byggnad Direkt, which is
the full building register and needs a legal review before access is granted
(HTTP 403 until then) — far more than is needed to draw footprints. See
[lantmateriet-byggnad.md](lantmateriet-byggnad.md) for why that was dropped.

- No key, no account, no legal review.
- Data is **ODbL**: wherever buildings are shown, credit
  "© OpenStreetMap contributors".
- It is community-mapped data, not an authoritative register. Coverage and
  detail vary by area.

## Endpoint

```text
GET /api/tempus/locales/{locale-id}/buildings/
```

Returns the building footprints clipped exactly to the Locale's geometry:

```json
{
  "locale": 42,
  "type": "FeatureCollection",
  "features": [
    {
      "collection": "openstreetmap",
      "feature_id": "way/256348441",
      "kind": "building",
      "properties": {"building": "yes", "source": "Bing"},
      "geometry": {"type": "Polygon", "coordinates": [[[15.4087, 60.4268], "..."]]}
    }
  ]
}
```

- `properties` is the OSM tag set, passed through **unchanged**
  (`building=yes|house|farm|...`, `name`, `building:levels`, ...). Most
  buildings only have `building` and `source`; do not depend on any other tag
  being present.
- `geometry` is a WGS 84 `Polygon` (or `MultiPolygon` where a footprint is
  cut by the Locale boundary), `[longitude, latitude]`.
- `feature_id` is `way/<OSM id>`, unique within a response.

Status codes: `503` if no Overpass URL is configured, `413` when the area
holds more than `OVERPASS_MAX_FEATURES` buildings (the request fails rather
than returning a partial layer), `429` when Overpass rate limits and retries
did not help, `502` on any other Overpass failure or if it stopped early.

The frontend normally reads buildings from the combined call
`GET /locales/{id}/land-cover/fetch/` instead (key `buildings`); see
[land-cover-fetch-handoff.md](land-cover-fetch-handoff.md). There it covers
the Locale's bounding box padded 5 km and is not clipped to the Locale shape.

## How it works

Overpass filters by bbox only. Tempus queries the geometry's bounding box

```text
way["building"]["building"!="no"](south,west,north,east); out geom qt;
```

and clips each footprint to the exact geometry with Shapely, like the land-
cover layer. Invalid rings are repaired, and only polygon parts of a clip are
kept. Code: `tempus/services/openstreetmap.py` (`buildings_in_geometry`).

## Verified live (2026-09-18)

Against overpass-api.de, for a small rural Locale with its 5 km padding
(about 11 × 11 km):

| Finding | Detail |
|---|---|
| Volume | 12 917 buildings; about 4.5 MB of stored JSON |
| Speed | The Overpass call took 1.9 s and 4.7 s in early runs, then 22.9 s and 24.5 s later; a following run got HTTP 504. Timing one slow run split it into **24.5 s waiting for Overpass (8.4 MB response) and 1.0 s of our own processing**, so the variation is on the public server's side, not in Tempus |
| Geometry | All ways were closed rings; clipping to a test triangle left nothing outside it |
| Rate limiting | The public instance answered **HTTP 429** after four queries within ~15 s from one IP |
| Retry | With retry-and-wait, queries that got a 429 succeeded after 18 s and 69 s |

Because 429 is real, the client retries 429/504 (`RETRIES`, default 3, waiting
10 s × attempt) before failing. The Locale prefetch is all-or-nothing, so one
failed source stops every layer from refreshing.

## Known limits

- **Relations are left out.** A building that is an OSM *multipolygon
  relation* (for example one with a courtyard) is not assembled. In the tested
  area that was 19 of about 11 300 (0.2 %). Only plain closed ways are drawn.
- **Payload size.** A populated area's buildings make the stored layer, and so
  the `land-cover/fetch/` response, several MB. Dense towns will be much
  larger; `OVERPASS_MAX_FEATURES` (default 30 000) is the safety cap.
- **Public server etiquette.** overpass-api.de is a shared, free service.
  Set `OVERPASS_USER_AGENT` to something that identifies this service, and
  consider a self-hosted or paid instance (`OVERPASS_URL`) if usage grows.
- How long a 429 lasts is not known; the default wait is a guess.
- **The public server can be slow or fail outright** (a query that took 2 s
  took 25 s later, and one run returned 504). Since the Locale prefetch is
  all-or-nothing, a failing Overpass call stops every layer for that run; the
  retries only cover 429/504. If this shows up in practice, a self-hosted or
  paid Overpass instance (`OVERPASS_URL`) is the fix.

## Place names

The same Overpass service also provides the `place_names` layer of the Locale
prefetch (`tempus/services/openstreetmap.py`, `place_names_in_geometry`). It
replaces a grid of Ortnamn Direkt lookups, which needed 100 requests and still
missed names, see [lantmateriet-ortnamn.md](lantmateriet-ortnamn.md#not-used-for-the-locale-prefetch).

```text
nwr["name"]["place"~"^(city|town|village|hamlet|isolated_dwelling|farm|locality|suburb|neighbourhood|quarter|island|islet)$"](south,west,north,east); out center tags qt;
```

- **One request** for the whole padded area, then a point-in-shape filter
  against the exact geometry. Nodes are points; ways and relations use their
  `center`.
- Each feature is a `Point` with `kind: "place_name"`,
  `feature_id: "node/123"` (or `way/`/`relation/`) and OSM's tags unchanged
  under `properties` (`name`, `place`, and whatever else the mapper added).
  **This is a different shape from the earlier Ortnamn-based `place_names`**
  (flat `namn`/`namntyp`/`kommunnamn`/... fields): read the name from
  `properties.name` and the type from `properties.place`.
- The place types kept are the ones worth labelling, including
  `isolated_dwelling` and `farm` (farm names). `city_block`, `block`, `square`
  and `municipality` are excluded: in the sampled rural area 104 of 236 named
  `place` objects were urban blocks.

Verified live (2026-09-18) on the same 11 × 11 km padded area used above:

| Finding | Detail |
|---|---|
| Coverage | 126 places: 49 hamlets, 49 neighbourhoods, 20 localities, 5 isolated dwellings, 1 village, 1 town, 1 islet |
| Requests | 1 |
| Speed | About 22 s. Three query shapes (regex on `place`, a union of exact values, nodes only) all took 21–23 s and gave the same result, so it is the public server's latency, not the query. The Locale prefetch is a background job, so this is not felt by a user, but two Overpass calls (buildings and place names) now run in each prefetch, which raises the chance of the 429 described above; the retry covers it. |

Not verified: how complete OSM's naming is compared with Lantmäteriet's
register in a given area (OSM Sweden's place names are mapper-contributed);
check a Locale you know before relying on it for every farm.

## Configuration

```env
OVERPASS_URL=https://overpass-api.de/api/interpreter
OVERPASS_USER_AGENT=origo-tempus
OVERPASS_TIMEOUT=120
OVERPASS_CACHE_SECONDS=2592000
OVERPASS_MAX_FEATURES=30000
```

Responses are cached per exact geometry (default 30 days).

## Implementation boundary

- Client: `tempus/services/openstreetmap.py` (`buildings_in_geometry`,
  `place_names_in_geometry`; both go through one shared `_overpass_elements`
  that owns the retry and "stopped early" handling)
- Live action: `tempus/views/reference.py` (`LocaleViewSet.buildings`)
- Prefetch: `tempus/services/locale_sources.py` (`SOURCES`, keys `buildings`
  and `place_names`), `tempus/models/land_cover.py`
  (`LandCoverFetch.buildings`, `LandCoverFetch.place_names`)
- Configuration: `origo/settings.py` (`OVERPASS_API`), `.env.example`
