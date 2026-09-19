# Frontend handoff: Tempus kartgenerator

## Scope

This handoff covers the map generator: the free visual basemap from OpenFreeMap,
Lantmäteriet Marktäcke Direkt point lookup and map surfaces, and optional
administrative-boundary overlays. It does **not** include roads, traffic data,
or routing.

The backend owns authentication to Lantmäteriet. The frontend uses the normal
authenticated Tempus API session and must never receive Lantmäteriet
credentials.

## Map API contract

Frontend needs no knowledge of Lantmäteriet's OAPIF service or its
credentials. There is no single combined map endpoint — initial setup comes
from one static endpoint, and each live layer (land cover, wetland,
administrative boundaries) is fetched from its own endpoint per viewport.
There used to be a combined `/api/tempus/map/` aggregator; it has been
removed in favour of this split, because the whole-country view it mainly
existed for turned out to need a static file, not a live aggregation.

### Initial view: the static country overview

Fetch once, at app start (it changes essentially never — cache it as long as
your HTTP client allows):

```http
GET /api/tempus/country-overview/
```

```json
{
  "basemap": {"provider": "OpenFreeMap", "style_url": "https://tiles.openfreemap.org/styles/liberty", "initial_view": {"center": [15.0, 62.0], "zoom": 4.5}},
  "outline": {"type": "Feature", "properties": {"kind": "country"}, "geometry": {"type": "MultiPolygon", "coordinates": []}},
  "waterways": {"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": {"kind": "lake", "objekttyp": "Sjö"}, "geometry": {"type": "Polygon", "coordinates": []}}
  ]},
  "land_cover": {
    "source": "schematic",
    "tiers": {
      "overview": {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"kind": "land_cover", "name": "Fjällkedjan", "objekttyp_group": "mountains"}, "geometry": {"type": "Polygon", "coordinates": []}}
      ]}
    }
  },
  "cities": [{"name": "Stockholm", "coordinates": [18.0686, 59.3293]}]
}
```

Use `basemap.style_url`/`basemap.initial_view` to initialise the renderer,
`outline` to draw Sweden's silhouette before any live layer has loaded,
`waterways` (`kind: "lake"` or `"river"`) for major lakes/rivers, `land_cover`
for a baked-in "where's the forest" overlay you can show immediately without
a live `/api/tempus/land-cover/` request, and `cities` for label points at
low zoom. The outline and major lakes carry real coastline/shoreline detail
(Natural Earth 1:10m), not a rounded-off silhouette — expect a visually busy
shape (skerries, narrow bays), not a smooth blob. Rivers remain schematic
source-to-mouth paths.

`land_cover.tiers` has a single `"overview"` resolution: a small, fixed set
of hand-drawn regions (`source: "schematic"`, not live/fetched data), the
same spirit as the hardcoded river paths in `waterways`. Live CORINE-backed
versions of this were tried and rejected (too much data, too slow, or a
visibly artificial grid of squares once made fast/accurate enough) — this is
explicitly just a rough visual impression at whole-country zoom, not a
land-use survey. `objekttyp_group` here uses a broader set of values than
the live degraded land-cover responses: `"mountains"`, `"dense_forest"`,
`"forest"`, `"agriculture"` — style each distinctly if useful, or collapse
`"dense_forest"`/`"forest"` to one forest style if not. Each feature also
carries a `name` (e.g. `"Fjällkedjan"`) for optional labelling. Expect a
handful of large, simple polygons, not fine-grained or precisely-bounded
regional detail — do not read boundaries between regions as accurate.

This is deliberately just decoration for the initial whole-country view, not
a land-use survey — there is no finer static tier, and none is planned.
Switch to the live `/api/tempus/land-cover/?bbox=...` endpoint once the user
has zoomed in enough that its own automatic fallback chain would return
`"summary"` or full detail — `land_cover` here is only ever this
one static, whole-country overview, it does not update with pan/zoom.

Do not use this endpoint for anything but the initial, whole-country render;
do not offer its `outline`/`waterways` as an "administrative boundary" layer
or its `land_cover` tiers as the live per-viewport land-cover layer, and do
not expect per-feature `properties` beyond what is shown above (`feature_id`/upstream
attributes do not apply to this endpoint).
A `503` means the file has not been generated on this deployment yet
(`manage.py generate_country_overview`); treat it like any other temporarily
unavailable layer, not a client error.

### Live layers: land cover, wetland, administrative boundaries

Each is its own endpoint, called directly per viewport — do not try to
recreate the old combined response client-side by calling all of them and
merging:

```http
GET /api/tempus/land-cover/?bbox={minLng},{minLat},{maxLng},{maxLat}
GET /api/tempus/administrative-boundaries/?bbox={minLng},{minLat},{maxLng},{maxLat}
```

Both take the same `bbox` (WGS 84, `minLng,minLat,maxLng,maxLat`) and an
optional `kinds` filter (comma-separated: `land_cover`/`wetland` for the
land-cover endpoint, `municipality`/`county`/`country` for the administrative
one). Fetch again only after a meaningful pan/zoom, not on every frame.

Use the app's existing Tempus API client for every request. Do not call
Lantmäteriet from the browser or add its keys to frontend environment
variables. Land cover is Lantmäteriet only — there is no other data source
or fallback provider.

## When to call it

Call the endpoint after the user has selected a Locale and picked a point on
the map. The point must be inside that Locale's `geometry`.

```http
GET /api/tempus/locales/{localeId}/land-cover/?longitude={longitude}&latitude={latitude}
```

Coordinates are WGS 84 in `[longitude, latitude]` order. Do not send latitude
first.

Example:

```text
/api/tempus/locales/42/land-cover/?longitude=18.0649&latitude=59.3293
```

## Response

```json
{
  "locale": 42,
  "point": {
    "type": "Point",
    "coordinates": [18.0649, 59.3293]
  },
  "land_cover": {
    "collection": "<upstream collection id>",
    "feature_id": "<upstream feature id>",
    "properties": {
      "objekttyp": "<Lantmäteriet classification>"
    }
  },
  "wetland": {
    "collection": "<upstream collection id>",
    "feature_id": "<upstream feature id>",
    "properties": {
      "objekttyp": "Sankmark, våt"
    }
  },
  "features": [
    "all matched upstream features, each with collection, feature_id and properties"
  ]
}
```

`land_cover` and `wetland` are independently nullable. Do not treat a missing
`wetland` as an error: it means that Lantmäteriet returned no sankmark feature
for the selected point.

`features` contains all upstream matches. Use it if the UI needs to show
multiple classifications or source details; it is not necessary for the basic
land-cover/sankmark presentation.

## Land-cover surfaces in the map response

For a general map, fetch land cover by current viewport. This endpoint is not
bound to a saved Locale:

```http
GET /api/tempus/land-cover/?bbox={minLng},{minLat},{maxLng},{maxLat}
```

It returns every authorized Lantmäteriet land-cover surface intersecting that
viewport, including wetland/sankmark surfaces (`kind: "land_cover"` and
`kind: "wetland"` in the same `features` array). Geometries are clipped to
the viewport so the frontend receives only what it can render. Request only
one surface type when needed:

```http
GET /api/tempus/land-cover/?bbox={minLng},{minLat},{maxLng},{maxLat}&kinds=wetland
```

At a country-scale viewport the full layer is too dense to fetch and render.
Rather than fail, the backend automatically falls back to a lighter
forest/agriculture-only overview (see "Degraded responses" below) up to a much
wider viewport. Only beyond that wider limit — or if the returned surfaces
would still exceed the maximum feature count — does the request return `413`.
That is the signal to defer the layer until the user zooms in further;
OpenFreeMap continues to provide the visual basemap at every zoom level.

Use the Locale-specific endpoint instead when a layer must be clipped to a
saved Locale:

```http
GET /api/tempus/locales/{localeId}/land-cover/map/
```

### Degraded responses (forest/agriculture overview)

The viewport `land_cover` layer (`/api/tempus/land-cover/?bbox=...`) can be
served in a reduced form instead of the full layer when the viewport is too
wide for the full layer. There are two reduced forms, tried in order, each
coarser than the last — both from Lantmäteriet, there is no other data
source. The response marks which one was used:

```json
{
  "type": "FeatureCollection",
  "degraded": true,
  "level": "summary",
  "features": [
    {
      "collection": "markytor",
      "feature_id": "<upstream feature id>",
      "kind": "land_cover",
      "objekttyp_group": "forest",
      "properties": {"objekttyp": "Barr- och blandskog"},
      "geometry": {"type": "Polygon", "coordinates": []}
    }
  ]
}
```

- `level: "summary"` — every forest/agriculture surface in the viewport,
  individually clipped and simplified, same shape as the full layer's
  features. Tried first once the viewport is too large for the full layer.
- `level: "overview"` — every forest surface merged into one polygon, and
  every agriculture surface merged into another, each simplified hard;
  `feature_id: null`, empty `properties` — they represent a dissolved
  region, not a single upstream surface — and geometry that can legitimately
  be a `MultiPolygon` spanning disjoint areas. The last fallback, used when
  `"summary"` itself fails or the viewport is too large even for it — if it
  also fails, the request errors as usual.

Both are only present together with `degraded: true`; a normal full response
has none of these keys at all — do not treat their absence as a falsy
default requiring special-casing, just check for `degraded`.

A degraded response of any level only ever contains
`objekttyp_group: "forest"` or `"agriculture"` features (no wetland, no other
land-cover types) — it is an overview, not a partial version of the full
layer. Treat it as its own rendering mode:

- Show a visible but unobtrusive indicator that the map is showing a reduced
  overview (e.g. "Förenklad kartvy — zooma in för fullständig marktäckning"),
  not an error state. Consider stronger wording for `level: "overview"`
  (e.g. "Kraftigt förenklad översikt") since it is visually coarser.
- Style by `objekttyp_group` (`forest` / `agriculture`) rather than by the
  finer `properties.objekttyp` values used in the full layer, since every
  degraded level collapses several source classes (e.g. both
  `Barr- och blandskog` and `Lövskog`) into `forest`.
- Do not read `feature_id` or `properties` for styling or identification on
  `level: "overview"` features — treat each as one opaque regional shape.
- Do not offer the per-type filters described under "Selection and filters"
  while showing a degraded response of any level; those apply to the full
  layer.
- Re-request the full layer as soon as the user zooms in enough that it would
  no longer be rejected, rather than waiting for the next unrelated refetch.

## Locale map surfaces

Fetch the full, clipped map layer for a selected Locale:

```http
GET /api/tempus/locales/{localeId}/land-cover/map/
```

The response is a GeoJSON `FeatureCollection`. Every geometry is clipped to
the Locale boundary server-side, so the frontend can render the features
directly without approximating or performing its own clipping.

```json
{
  "locale": 42,
  "type": "FeatureCollection",
  "features": [
    {
      "collection": "<upstream collection id>",
      "feature_id": "<upstream feature id>",
      "kind": "land_cover",
      "properties": {"objekttyp": "Skog"},
      "geometry": {"type": "Polygon", "coordinates": []}
    },
    {
      "collection": "<upstream collection id>",
      "feature_id": "<upstream feature id>",
      "kind": "wetland",
      "properties": {"objekttyp": "Sankmark, våt"},
      "geometry": {"type": "Polygon", "coordinates": []}
    }
  ]
}
```

Render `kind: "land_cover"` and `kind: "wetland"` as separate GeoJSON data
sources/layers. The properties remain the source of truth for labels, colours,
and future filters. The response is cached on the backend for 30 days by
default, persistently (a database-backed cache, not tied to one server
process).

The endpoint returns `413` rather than an incomplete layer if the selected
Locale exceeds the configured maximum number of source features. In that state,
offer the point lookup or a smaller saved Locale; do not render a partial layer.

## Suggested presentation

After a successful lookup, show a compact result panel associated with the map
marker:

| Field | Display rule |
|---|---|
| Chosen point | Render the user-selected coordinates or marker label. |
| Marktäcke | Show `land_cover.properties.objekttyp` when available; otherwise show the available properties without inventing a label. |
| Sankmark | Show the Sankmark `objekttyp` when `wetland` exists; otherwise show “Ingen sankmark registrerad”. |
| Additional information | Make the remaining `properties` values expandable. |

Keep the original property keys and values available in the UI. Lantmäteriet is
the source of truth and may expose classifications beyond the initial design.

## Selection and filters

Build future selectors from values actually returned in `properties` rather
than from a fixed frontend enum. In particular:

- use the returned `objekttyp` values for land-cover and wetland choices;
- represent `wetland !== null` as a separate “sankmark” filter;
- preserve unknown values so newly available Lantmäteriet classes remain
  usable without a frontend release.

For a viewport-based selection by specific `objekttyp` values, use the
dedicated endpoint instead of filtering the full layer's response
client-side:

```http
GET /api/tempus/land-cover-by-type/?bbox={minLng},{minLat},{maxLng},{maxLat}&types={objekttyp},{objekttyp},...
```

`types` is required: a comma-separated list of exact, case-sensitive
`objekttyp` values (e.g. `types=Barr- och blandskog,Åker`) — build the list
from values already seen in `land-cover/` responses, not a hardcoded
frontend enum. Filtering happens server-side at Lantmäteriet, so this is
cheaper than fetching the full layer and filtering locally when only a
narrow selection is needed. Same response shape, `bbox`/`kinds` handling,
and viewport-size limit as `land-cover/`'s full-detail tier — but no
degraded fallback tier of its own, so a too-large viewport returns `413`
rather than a coarser result. Filtering across a whole saved Locale (rather
than a viewport) is not implemented yet.

## States and error handling

| Backend result | Frontend behavior |
|---|---|
| Loading | Show a small loading state at the selected map point; disable duplicate requests for the same point. |
| `200` | Update the marker result panel with `land_cover` and `wetland`. |
| `400` | Explain that the selected point must be a valid coordinate inside the selected Locale. |
| `404` | Show “Ingen marktäckesinformation hittades för denna punkt.” |
| `429` | Show a retryable "too many requests" state and respect the `Retry-After` header (seconds) before retrying automatically. |
| `502` | Show a retryable upstream-service error. |
| `503` | Show that the land-cover service is temporarily unavailable; do not expose configuration details. |

For a viewport map response, handle `413` by asking the user to zoom in or
choose a smaller viewport rather than rendering only part of the data. Handle
a `200` with `degraded: true` per "Degraded responses" above — it is a
successful response, not an error state.

Cancel or ignore an older in-flight request when the user places another map
marker, so a slower response cannot overwrite the result for the newest point.

## Administrative boundaries in the map response

OpenFreeMap supplies the visual country outline and coastline, and the static
`/api/tempus/country-overview/` supplies a generalised Sweden outline for the
initial view (see above). Fetch administrative boundaries only as an
optional, live Tempus overlay for the current viewport:

```http
GET /api/tempus/administrative-boundaries/?bbox={minLng},{minLat},{maxLng},{maxLat}
```

`bbox` is required and uses WGS 84 in `minLng,minLat,maxLng,maxLat` order. The
response is a GeoJSON `FeatureCollection`, clipped to that viewport, and
detail scales down automatically as the bbox widens: municipality outlines
only appear below roughly a 2° bbox, county outlines below roughly 6°, and
above that only the (live, per-viewport) country boundary is included —
prefer the static overview's `outline` over this live `kind: "country"`
result for a whole-country render; they are generated independently and may
not look identical. The locale-specific endpoint remains available when a
layer must be clipped to a saved Locale:

```http
GET /api/tempus/locales/{localeId}/administrative-boundaries/
```

```json
{
  "bbox": [10.0, 55.0, 25.0, 70.0],
  "type": "FeatureCollection",
  "features": [
    {
      "collection": "<upstream collection id>",
      "feature_id": "<upstream feature id>",
      "kind": "municipality",
      "properties": {"...": "upstream attributes"},
      "geometry": {"type": "Polygon", "coordinates": []}
    }
  ]
}
```

Use `kind` to style municipalities, counties, and the country boundary
independently. Preserve `properties` for labels and future selection/filtering.
The backend caches this layer briefly and fetches only the requested viewport.

## Implementation and test checklist

Use fixture responses matching the examples in this document for component and
map-rendering tests. The frontend does not need a live Lantmäteriet account to
test styling, layer toggles, error states, or request cancellation.

- Initialise the renderer from `/api/tempus/country-overview/`
  (`basemap.style_url`, `outline`, `waterways`, `cities`) before any bbox is
  known. For land cover and administrative boundaries, load only when the
  layer toggle is enabled and retain a response while the viewport remains
  within its bbox.
- Test `/api/tempus/country-overview/` returning `503` (not yet generated on
  this deployment): show the basemap alone rather than blocking the map.
- Test `land_cover.tiers.overview` rendering its handful of large, simple
  regions (`mountains`/`dense_forest`/`forest`/`agriculture`) with distinct
  styling per `objekttyp_group`, and confirm the `name` property is
  available for optional labelling.
- Treat every `geometry` as GeoJSON in WGS 84 (`[longitude, latitude]`). Do
  not reverse coordinate order.
- Style land cover from `kind` and source `properties`; style administrative
  features from `kind` values such as `municipality`, `county`, and `country`.
- Render unknown `kind` values safely with a neutral administrative-boundary
  style rather than dropping source data.
- Test `200` with an empty `features` array: this is a valid empty layer, not
  an error.
- Test bbox validation (`400`): missing, non-numeric, reversed, or non-WGS 84
  bounds must not be sent to the API.
- Test `401`/`403` by returning the normal Tempus login/permission state; the
  frontend must not retry against Lantmäteriet directly.
- Test `429`, `502`, and `503` with a retryable “Kartdata är tillfälligt
  otillgänglig” state, honouring `Retry-After` on `429`. For land-cover
  surfaces, also test `413` and prompt for a smaller viewport.
- Test a `200` land-cover viewport response with `degraded: true,
  level: "summary"` and only `objekttyp_group: "forest"`/`"agriculture"`
  features: render the reduced overview style and indicator, not the
  full-layer styling or filters.
- Test `degraded: true, level: "overview"` with at most one forest and one
  agriculture feature, `feature_id: null`, and a `MultiPolygon` geometry:
  render it as one opaque shape per group, not per-surface styling.
- Test `/api/tempus/land-cover-by-type/` with a `types` selection: same
  rendering as `land-cover/`'s full-detail response, and a `400` when
  `types` is missing.
- Cancel or disregard an in-flight marker request when the marker is moved or
  the selected Locale changes.

Before enabling the layer in a deployed UI, perform one authenticated
integration request for each endpoint against the configured backend. This
verifies the account authorization and source data; these upstream calls have
not been replaced by frontend mocks.

## Out of scope

- Roads and traffic information
- Route planning
- Server-side filtered land-cover search across a whole saved Locale (only
  viewport-based filtering via `land-cover-by-type/` exists)
- Persisting Lantmäteriet results in the Tempus database
- Exposing Lantmäteriet credentials to the browser
