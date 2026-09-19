# Lantmäteriet: Marktäcke och administrativa gränser

Tempus can look up Lantmäteriet's current land-cover classification at a point
inside a user's Locale. The integration uses **Marktäcke Direkt**, an OGC API
Features service; it does not use the STAC/GeoPackage download product.

The upstream service is authoritative. Tempus does not store a copy of its
geometries or classification values in the database.

## Locale point lookup

```text
GET /api/tempus/locales/{locale-id}/land-cover/?longitude={longitude}&latitude={latitude}
```

The endpoint is available only to authenticated users and a Locale can only be
read by its owner. Coordinates are WGS 84 in GeoJSON order: longitude first,
latitude second.

The query point must be inside the Locale's `MultiPolygon`. The endpoint
returns `400` for missing, non-finite, out-of-range, or out-of-locale
coordinates; `404` when Lantmäteriet has no feature at that location; `502` on
an upstream failure; and `503` when the integration lacks configuration.

Example:

```http
GET /api/tempus/locales/42/land-cover/?longitude=18.0649&latitude=59.3293
```

## Response contract

```json
{
  "locale": 42,
  "point": {"type": "Point", "coordinates": [18.0649, 59.3293]},
  "land_cover": {
    "collection": "<Lantmäteriet collection id>",
    "feature_id": "<upstream feature id>",
    "properties": {"...": "upstream attributes"}
  },
  "wetland": {
    "collection": "<Lantmäteriet collection id>",
    "feature_id": "<upstream feature id>",
    "properties": {"objekttyp": "Sankmark, våt"}
  },
  "features": ["all matched upstream features"]
}
```

`land_cover` or `wetland` can be `null`. `wetland` is populated when the
collection name or an upstream attribute identifies the feature as
`Sankmark`. Lantmäteriet's source attributes are preserved under `properties`;
Tempus does not translate, rename, or hard-code the classification taxonomy.

`features` contains every returned feature. It is included so clients can use
additional Lantmäteriet layers without a backend contract change.

## Locale map surfaces

```text
GET /api/tempus/locales/{locale-id}/land-cover/map/
```

This endpoint returns every matching Lantmäteriet feature as a GeoJSON-like
feature object with `collection`, `feature_id`, `kind`, `properties`, and a
`geometry`. The geometry is intersected with the Locale `MultiPolygon` on the
server, so no returned surface extends outside the selected Locale.

`kind` is `land_cover` or `wetland`. The latter is assigned when Lantmäteriet
identifies a feature as `Sankmark`. The response wrapper is a GeoJSON
`FeatureCollection` and includes the Locale ID.

The request is cached for 30 days by default, persistently (Django's database
cache — see "Caching" below), not just for the life of one worker process. It
follows all upstream pagination links and fails with `413` rather than
returning a partial map when the configured feature limit is exceeded.
Configure the cache, upstream page size, and safety limit with the
`LANTMATERIET_MARKTACKE_MAP_*` variables in `.env.example`.

## Authentication and configuration

Set secrets only in the deployed environment or local `.env`; never commit or
send them in chat.

Private Geotorget customers use Basic authentication — confirmed sufficient
on its own by Lantmäteriet's own documentation ("Bli konsument som
privatperson": private accounts get Basic auth only, no OAuth option), not
just a fallback:

```env
LANTMATERIET_MARKTACKE_USERNAME=<Geotorget username>
LANTMATERIET_MARKTACKE_PASSWORD=<Geotorget password>
```

An account with a manually obtained API Portal access token can instead set
`LANTMATERIET_MARKTACKE_ACCESS_TOKEN`. An OAuth2 client-credentials flow
(`TOKEN_URL`/`CLIENT_ID`/`CLIENT_SECRET`) used to be supported here too; it
was removed 2026-09-17 — it had never been exercised against a real token
endpoint in this codebase, and its token cache key was hardcoded and shared
across every Lantmäteriet product, a latent collision once a second provider
(e.g. Trafikverket) reused `_authorization_header`. Reintroduce it
deliberately and verified if a real need for it shows up.

```env
# Optional: defaults to the production Marktäcke Direkt endpoint.
LANTMATERIET_MARKTACKE_BASE_URL=https://api.lantmateriet.se/ogc-features/v1/marktacke
LANTMATERIET_MARKTACKE_TIMEOUT=15

# Optional: limit requests to named upstream collections. Leave unset to
# discover every collection that the authenticated account can access.
LANTMATERIET_MARKTACKE_COLLECTION_IDS=
```

The client obtains available collection IDs from the authenticated
`GET {BASE_URL}/collections` response when no allow-list is set. This avoids
hard-coding product metadata or requiring a user to discover IDs manually.

## Selectable fields

Future filters and UI selectors must be derived from the actual values in
`land_cover.properties`, `wetland.properties`, or the items in `features`.
This permits selecting current Lantmäteriet classifications such as land-cover
type, sankmark status, or wet/firm wetland subtype without a database
migration. Do not replace the raw properties with a local enum unless a
product decision defines the supported vocabulary and its update policy.

## Kommun-, läns- och riksgränser

Tempus also supports the separately authorized **Kommun, Län och Rike Direkt**
product as an optional administrative overlay. It is not used as a visual
country outline; the map renderer uses the configured OpenFreeMap vector-tile
style for coastline and basemap information. Use the viewport-based endpoint
for municipality/county/country data without a saved Locale:

```text
GET /api/tempus/administrative-boundaries/?bbox={minLon},{minLat},{maxLon},{maxLat}
```

`bbox` is WGS 84 and required. Returned geometries are clipped to that bbox.
An optional `kinds=municipality,county,country` parameter restricts the layer.
The result is a `FeatureCollection` with the requested `bbox` and feature
objects containing `collection`, `feature_id`, `kind`, `properties`, and
`geometry`.

For a saved Locale, the narrower endpoint remains available:

```text
GET /api/tempus/locales/{locale-id}/administrative-boundaries/
```

It returns a `FeatureCollection` whose geometries are transformed to WGS 84
and clipped to the Locale boundary. Each item has `collection`, `feature_id`,
`kind`, `properties`, and `geometry`. `kind` is normally `municipality`,
`county`, or `country`.

The product is an OGC API Features service. Tempus requests only the relevant
features for the requested viewport or Locale extent, clips them server-side,
and returns GeoJSON. Results are cached briefly by default. Nothing is
persisted in the Tempus database and no country-sized download is made.

The same Lantmäteriet credentials configured for Marktäcke are used. Its
product authorization must also be active on that account. OAPIF collections
are discovered from the authorized account; use
`LANTMATERIET_ADMINISTRATIVE_BOUNDARIES_COLLECTION_IDS` only if a deployment
needs to restrict it explicitly.

## Viewport map surfaces

There is no combined map endpoint. Each Tempus overlay is its own viewport
endpoint, called directly with a `bbox`:

```text
GET /api/tempus/land-cover/?bbox={minLon},{minLat},{maxLon},{maxLat}
GET /api/tempus/administrative-boundaries/?bbox={minLon},{minLat},{maxLon},{maxLat}
```

Each returns an independently renderable GeoJSON `FeatureCollection`. `bbox`
is required and uses WGS 84 order; both accept an optional `kinds` filter.
Each geometry is clipped to `bbox` rather than to a saved Locale. This is a
dynamic map-data API: the client requests it as the user zooms and pans. It is
not a tile service and deliberately returns `413` when a viewport exceeds the
configured feature safety limit — the land-cover endpoint instead degrades to
a coarser Lantmäteriet-derived forest/agriculture overview first (`summary`,
then `overview`) rather than erroring outright; see the frontend handoff doc.
Lantmäteriet only — there is no other data source or fallback provider.

### Filtering by land-cover type

```text
GET /api/tempus/land-cover-by-type/?bbox={minLon},{minLat},{maxLon},{maxLat}&types={objekttyp},{objekttyp},...
```

Returns only the requested `objekttyp` surfaces, filtered **server-side by
Lantmäteriet** (a CQL2 `objekttyp IN (...)` filter) rather than fetched in
full and filtered locally. `types` is required: a comma-separated list of
exact, case-sensitive `objekttyp` values (e.g.
`types=Barr- och blandskog,Åker`) — there is no local enum of valid values;
use whatever values `land-cover/` itself returns in `properties.objekttyp`.
`kinds=land_cover,wetland` is accepted the same as on `land-cover/`. Subject
to the same viewport-size limit as `land-cover/`'s full-detail tier (see
`LANTMATERIET_MARKTACKE_MAP_MAX_FEATURES` etc.) and has no degraded fallback
tier of its own — a selection this specific has no meaningful coarser
substitute, so a too-large viewport returns `413` rather than a partial or
generalised result.

A combined `/api/tempus/map/` endpoint previously existed but was removed: it
mainly existed to serve the whole-country view, which turned out to need a
static, pre-generalised file rather than a live Lantmäteriet request on every
cache miss (see "Whole-country overview" below).

## Whole-country overview

The initial, whole-Sweden view (outline, major lakes/rivers, a hand-drawn
land-use overview, major cities, and the visual basemap config) is served
from a static file, not a live request:

```text
GET /api/tempus/country-overview/
```

This is deliberate: Sweden's outline does not meaningfully change between
deployments, and Lantmäteriet's full-resolution coastline (archipelago
included) is too large to fetch as a live request just to build this file.
The file is generated offline, once, with:

```text
python manage.py generate_country_overview
```

The outline itself comes from Natural Earth's public-domain 1:10m Admin 0
countries dataset (its most detailed tier), not Lantmäteriet: Lantmäteriet's
own administrative boundaries ("Kommun, Län och Rike Direkt") describe
jurisdictional area, which extends into territorial water and does not match
actual land area, and its accurate `markytor` land-cover collection is far
too large to fetch for a whole country just to build this outline. Natural
Earth's coarser 1:50m/1:110m tiers were tried and rejected too: both throw
away real coastline detail (narrow bays, inlets, and — at 1:110m — Gotland
and Öland entirely) before the file is ever downloaded. 1:10m is used
deliberately to keep that detail; the command only drops the very smallest
specks (a configurable minimum area) and fixes up any invalid geometry left
behind by simplification, rather than smoothing the coastline into a rounder
but less accurate shape. Major lakes come from the same Natural Earth 1:10m
tier's lakes dataset, looked up by name (a hardcoded name list — Vänern,
Vättern, Mälaren, Hjälmaren, Storsjön, Siljan; real geometry, not a schematic
shape), with the same light-touch treatment. Major rivers remain a small
hardcoded set of schematic source-to-mouth paths, since Natural Earth does
not carry named Swedish rivers at this tier.

The land-cover overview is now a small set of hand-drawn, approximate
regions (`LAND_REGIONS` in the command) — the same spirit as the hardcoded
`MAJOR_RIVERS` paths, not live data. Three CORINE-backed live approaches
were tried and rejected in turn before this: a per-parcel dissolve (tens of
thousands of individual parcel features — far too much data and too slow),
a coarse grid classified by forest/agriculture *presence* (confirmed live:
classified nearly the whole country as forest, since some forest exists
almost everywhere at that resolution), and the same grid classified by area
*dominance* instead (correct, but still rendered as a visibly blocky grid of
squares and was still too slow doing hundreds of live requests one at a
time). None of that overhead is worth it for what is explicitly just a rough
visual impression at whole-country zoom, not a land-use survey — four
regions (`mountains`, `dense_forest`, `forest`, `agriculture`) drawn by hand
and clipped to the real outline give a similar impression instantly, with no
API calls, no caching, and nothing to go wrong at generation time.

Pass `--skip-land-cover` to regenerate the file without it. A hardcoded list
of Sweden's largest cities plus `TEMPUS_MAP_BASEMAP` are also bundled.
Regenerate it (and commit the result) when Natural Earth publishes a new
edition, or when the generation thresholds or `LAND_REGIONS` are retuned —
there is no scheduled regeneration, and the endpoint serves whatever was
last committed.

## Visual basemap

The visual basemap is deliberately separate from the Lantmäteriet overlays.
`GET /api/tempus/country-overview/` includes the configured
[OpenFreeMap vector-tile style](https://openfreemap.org/quick_start/) in
`basemap.style_url`, together with its attribution and initial view. The
frontend loads that public style directly in its map renderer. This provides
the visual coast and country outline for the basemap layer itself; the
`outline`/`waterways` fields in the same response are Tempus's own generalised
Lantmäteriet-derived geometry, layered on top, not a coastline substitute for
either source.

The default style is `https://tiles.openfreemap.org/styles/liberty`. A
deployment can override it with `TEMPUS_MAP_BASEMAP_STYLE_URL`; no map tiles or
whole-country raster data are stored or proxied by Tempus.

## Caching

Every map/viewport response above (`land-cover/`, `land-cover-by-type/`,
`administrative-boundaries/`, and the Locale-scoped equivalents) is cached in
Django's shared cache, keyed by the exact request parameters (bbox,
collections, filter, simplification tolerance). Concurrent identical
requests are coalesced into a single upstream call (`_cache_singleflight` in
`lantmateriet.py`) rather than each independently hitting Lantmäteriet and
risking its rate limit.

The default cache backend (`origo/settings.py`) is Django's `DatabaseCache`,
not an in-memory cache: this data is meant to persist across restarts/deploys
and be shared between worker processes, which an in-process cache cannot do.
It requires the cache table to exist — run `manage.py createcachetable` once
per environment (and again if the cache `LOCATION` in settings changes).
Setting `REDIS_URL` switches to Redis instead, with a much shorter default
TTL (`CACHES["default"]["TIMEOUT"]`, 300s) — the two backends are not
interchangeable defaults, only alternatives.

## Implementation boundary

- HTTP client: `tempus/services/lantmateriet.py`
- Locale action: `tempus/views/reference.py`
- Configuration: `origo/settings.py`
- Environment-variable reference: `.env.example`

Place names (Ortnamn Direkt) and buildings (Byggnad Direkt) are separate,
non-OGC-Features Lantmäteriet products layered on the same Locale endpoints
— see [lantmateriet-ortnamn.md](lantmateriet-ortnamn.md) and
[lantmateriet-byggnad.md](lantmateriet-byggnad.md).

External requests happen only when one of the three Lantmäteriet Locale
actions is called. No Lantmäteriet request occurs during a model save,
serializer validation, or Locale list/detail response.
