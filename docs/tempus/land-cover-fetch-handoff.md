# Frontend handoff: background land-cover prefetch per Locale

## Scope

This handoff covers one endpoint:

```http
GET /api/tempus/locales/{localeId}/land-cover/fetch/
```

It reports the status and result of a background job that automatically
fetches **land-cover, hydrography** (Lantmäteriet), **place-name, building**
(OpenStreetMap) and **road** (Trafikverket) data for the area around a saved
Locale — the Locale's own bounding box, padded 5 km in every direction. The job runs
asynchronously and needs no action from the frontend to start: it is queued
whenever a Locale is created or its `geometry` changes.

The layers come from separate products, fetched together by this one job
(the list of sources lives in `tempus/services/locale_sources.py`, see
[adding-a-locale-data-source.md](adding-a-locale-data-source.md#the-source-registry)):

- **Land cover** (`land_cover` in the response) — Marktäcke Direkt: forest,
  agriculture, and other surface classification, plus wetland. Sea surface is
  included here, as an `objekttyp: "Hav"` feature — Lantmäteriet has no
  separate "sea" product; it is just one of Marktäcke's land-cover classes.
- **Hydrography** (`hydrography` in the response) — the separate Hydrografi
  product: lakes, watercourses, and the coastline/land-water boundary. There
  is no sea-surface polygon here; use `land_cover`'s `"Hav"` features for sea
  surface, and `hydrography`'s `kind: "coastline"` features for the
  shoreline.
- **Place names** (`place_names` in the response) — OpenStreetMap via
  Overpass (see [openstreetmap-buildings.md](openstreetmap-buildings.md#place-names)):
  villages, hamlets, farms (`isolated_dwelling`/`farm`), localities and the
  like, as points, for the whole padded area in one request. Lantmäteriet's
  Ortnamn Direkt is not used for this layer because it cannot be queried by
  area (see [lantmateriet-ortnamn.md](lantmateriet-ortnamn.md#not-used-for-the-locale-prefetch)).
- **Buildings** (`buildings` in the response) — OpenStreetMap building
  footprints via Overpass (see
  [openstreetmap-buildings.md](openstreetmap-buildings.md)). Unlike place
  names, this **is** an exact clip of the full padded area: queried by bbox
  and clipped to the padded rectangle. Community-mapped data under the ODbL —
  credit "© OpenStreetMap contributors" where buildings are shown. Buildings
  mapped as multipolygon relations are not included (about 0.2 % in the
  tested area).
- **Roads** (`roads` in the response) — Trafikverket's NVDB road segments
  (see [trafikverket-roads.md](trafikverket-roads.md)). A different provider
  from the rest, and an exact clip like buildings: queried by bbox, then
  clipped to the padded area. Only currently valid segments are included.

This is a **separate process** from the existing per-Locale map layer. Do not
conflate the two:

| | `GET .../land-cover/map/` | `GET .../land-cover/fetch/` |
|---|---|---|
| Area | Exactly the Locale's own geometry | Locale's bounding box + 5 km padding |
| Trigger | Synchronous, fetched (and cached) on request | Asynchronous, auto-queued on Locale save |
| Clipping | Clipped exactly to the Locale boundary | Clipped to the padded bounding box, not the Locale shape |
| Purpose | The precise map layer for the saved area | Wider surrounding context, fetched ahead of time |

Use `land-cover/map/` for the map layer described in
[marktacke-frontend-handoff.md](marktacke-frontend-handoff.md). Use
`land-cover/fetch/` only when a feature specifically needs the wider,
pre-fetched context (e.g. showing what's just outside the Locale boundary).
If no feature needs that yet, there is nothing to build against this endpoint
beyond a status indicator.

## Request

```http
GET /api/tempus/locales/{localeId}/land-cover/fetch/
```

No query parameters. Requires the normal authenticated Tempus session; only
returns data for Locales owned by the current user (same ownership scoping as
the rest of `locales/`).

## Calling it from the frontend

This is the **one combined call** for a Locale's surrounding map data: when
`status` is `"succeeded"` the response carries every layer — `land_cover`,
`hydrography`, `place_names`, `buildings` and `roads` — so the frontend does
not make one request per layer. Read each layer off the same response object.

- No body, no query parameters, no CSRF token (GET). Send the session cookie
  (`credentials: "include"`).
- The call is cheap: it only reads the stored row, it never contacts Lantmäteriet
  or Trafikverket. That is why polling it is fine.
- The layers are only present when `status === "succeeded"`. Before that the
  response has just `locale` and `status` (plus timestamps).
- The response is always HTTP `200` once the Locale is yours; a failed
  background job is `status: "failed"` with an `error`, not an HTTP error.

Use the app's existing Tempus API client for this, like the other Locale calls.
As a plain `fetch` with polling it looks like:

```ts
async function loadSurroundings(localeId: number, signal: AbortSignal) {
  for (;;) {
    const res = await fetch(`/api/tempus/locales/${localeId}/land-cover/fetch/`, {
      credentials: "include",
      signal, // AbortController — abort when the user switches Locale
    });
    if (!res.ok) throw new Error(String(res.status)); // 401/403/404: normal Tempus handling

    const data = await res.json();

    if (data.status === "succeeded") {
      const { land_cover, hydrography, place_names, buildings, roads, geometry } = data;
      return { land_cover, hydrography, place_names, buildings, roads, geometry };
    }
    if (data.status === "failed") throw new Error(data.error); // stop; no manual retry exists

    // "missing" | "pending" | "running": wait a few seconds and ask again
    await new Promise((resolve) => setTimeout(resolve, 3000));
  }
}
```

Each layer is a GeoJSON-style `FeatureCollection` (see the per-layer shapes
below). Every feature has `feature_id`, `kind`, `properties` (the upstream
record, passed through unchanged) and `geometry`. All coordinates are WGS 84
`[longitude, latitude]`, and every layer covers the same padded rectangle
given in `geometry`.

Cancel or ignore an in-flight request when the selected Locale changes, so a
slow response for the previous Locale cannot overwrite the current one.

## Response

`200` in every case — a missing or not-yet-run fetch is reported as a status
value, not an HTTP error.

### No fetch has run yet

```json
{
  "locale": 42,
  "status": "missing"
}
```

`"missing"` means the background job has not produced a row for this Locale
yet — most likely a Locale saved before this feature existed, or the
background worker has not processed the queue yet. Treat it the same as
`"pending"` in the UI (see below); do not treat it as an error.

### Pending / running

```json
{
  "locale": 42,
  "status": "pending",
  "buffer_metres": 5000,
  "geometry": {},
  "created_at": "2026-09-17T10:00:00Z",
  "started_at": null,
  "finished_at": null
}
```

`geometry` is the *previous* successful fetch's padded area, if any (empty
`{}` before the first run ever completes) — while `status` is `"pending"` or
`"running"`, do not read `geometry` as the area currently being fetched.

### Succeeded

```json
{
  "locale": 42,
  "status": "succeeded",
  "buffer_metres": 5000,
  "geometry": {
    "type": "Polygon",
    "coordinates": [[[17.97, 59.27], [18.16, 59.27], [18.16, 59.37], [17.97, 59.37], [17.97, 59.27]]]
  },
  "created_at": "2026-09-17T10:00:00Z",
  "started_at": "2026-09-17T10:00:01Z",
  "finished_at": "2026-09-17T10:00:04Z",
  "land_cover": {
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
        "kind": "land_cover",
        "properties": {"objekttyp": "Hav"},
        "geometry": {"type": "Polygon", "coordinates": []}
      }
    ]
  },
  "hydrography": {
    "type": "FeatureCollection",
    "features": [
      {
        "collection": "StandingWater",
        "feature_id": "<upstream feature id>",
        "kind": "lake",
        "properties": {"localType": "sjö", "surfaceArea": 146067},
        "geometry": {"type": "Polygon", "coordinates": []}
      },
      {
        "collection": "WatercourseLine",
        "feature_id": "<upstream feature id>",
        "kind": "watercourse",
        "properties": {},
        "geometry": {"type": "LineString", "coordinates": []}
      },
      {
        "collection": "LandWaterBoundary",
        "feature_id": "<upstream feature id>",
        "kind": "coastline",
        "properties": {},
        "geometry": {"type": "LineString", "coordinates": []}
      }
    ]
  },
  "place_names": {
    "type": "FeatureCollection",
    "features": [
      {
        "collection": "openstreetmap",
        "feature_id": "node/244464656",
        "kind": "place_name",
        "properties": {"name": "Floda", "place": "hamlet"},
        "geometry": {"type": "Point", "coordinates": [15.3192, 60.4331]}
      }
    ]
  },
  "buildings": {
    "type": "FeatureCollection",
    "features": [
      {
        "collection": "openstreetmap",
        "feature_id": "way/256348441",
        "kind": "building",
        "properties": {"building": "yes", "source": "Bing"},
        "geometry": {"type": "Polygon", "coordinates": []}
      }
    ]
  },
  "roads": {
    "type": "FeatureCollection",
    "features": [
      {
        "collection": "Vägnummer",
        "feature_id": 8629229,
        "kind": "road",
        "properties": {"GID": 8629229, "Huvudnummer": 50, "Undernummer": 0, "Valid_To": "9999-12-31", "...": "other upstream attributes"},
        "geometry": {"type": "LineString", "coordinates": [[15.4157, 60.4817], [15.4154, 60.4816]]}
      }
    ]
  }
}
```

`geometry` is the exact rectangle (a GeoJSON `Polygon`, always axis-aligned)
that was fetched: the Locale's bounding box padded by `buffer_metres` in
every direction — **not** clipped to the Locale's own shape, unlike
`land-cover/map/`. `land_cover` has the same feature shape as
`land-cover/map/`'s response (`collection`, `feature_id`, `kind`,
`properties`, `geometry` per feature; `kind` is `"land_cover"` or
`"wetland"`; sea surface is `kind: "land_cover"` with
`properties.objekttyp: "Hav"`).

`hydrography` uses the same per-feature shape, but its own `kind` values:
`"lake"` (Standing Water, polygon), `"watercourse"` (rivers/streams, line or
polygon depending on width), and `"coastline"` (the land-water boundary,
always a line — do not expect a filled sea polygon from this key). Lake
properties commonly include `localType` (`"sjö"`) and `surfaceArea`
(square metres); watercourse and coastline properties are often empty and
should be treated as opaque, not relied on for labelling.

`place_names` features are `Point`s from OpenStreetMap with `kind:
"place_name"` and OSM's tags under `properties`: the name is
`properties.name` and the type `properties.place` (`village`, `hamlet`,
`isolated_dwelling`, `farm`, `locality`, `neighbourhood`, ...; see
[openstreetmap-buildings.md](openstreetmap-buildings.md#place-names)). This is
**not** the shape of the Ortnamn-based `place-names/search/` endpoint (flat
`namn`/`namntyp`/... fields) — the two differ, so don't share a component
between them. Coverage is complete for the area as far as OSM is; it is
mapper-contributed, so a name can be missing if nobody has mapped it.

`buildings` features use `kind: "building"`, `feature_id` `way/<OSM id>`, and
pass the OSM tags through **unchanged** under `properties` (most buildings only
have `building` and `source`; depend on no other tag). Geometries are WGS 84
`Polygon`s (`MultiPolygon` where the padded rectangle cuts a footprint).
This field is a full, exact clip of the padded area, but it can be several MB
in a built-up area (see [openstreetmap-buildings.md](openstreetmap-buildings.md)).

`roads` features use `kind: "road"` and pass Trafikverket's attributes
through unchanged under `properties` (road number `Huvudnummer`/`Undernummer`,
county `Länstillhörighet`, `Europaväg`, and linear-referencing fields such as
`Start_Measure`/`Seq_No`). Geometries are 2D `LineString`s (or
`MultiLineString` where a segment leaves and re-enters the area); elevation is
dropped. A road segment that straddles the padded rectangle appears clipped at
its edge, like every other layer.

### Failed

```json
{
  "locale": 42,
  "status": "failed",
  "buffer_metres": 5000,
  "geometry": {},
  "created_at": "2026-09-17T10:00:00Z",
  "started_at": "2026-09-17T10:00:01Z",
  "finished_at": "2026-09-17T10:00:02Z",
  "error": "The requested map area contains too many Marktäcke Direkt features to render in one response."
}
```

`error` is a human-readable message from the backend (already Swedish/English
mixed depending on the underlying failure) — safe to show directly or behind
a generic wrapper, but not guaranteed to be a stable machine-readable code.

## Polling

There is no push notification for this job finishing. Poll on an interval
(a few seconds) only while `status` is `"pending"`, `"running"`, or
`"missing"`; stop polling once it is `"succeeded"` or `"failed"`. Re-poll only
after the user edits the Locale's geometry again (which re-queues the job).

## Re-fetching behavior

Saving a Locale (create or update) always re-queues the background job, but
the job itself skips every upstream call when the previously fetched area
already fully covers the Locale's current padded bounding box — e.g. renaming
a Locale or editing an unrelated field does not trigger a new upstream
request, and `status` may go straight from `"succeeded"` back to
`"succeeded"` without a `"running"` step in between. A boundary edit that
actually moves or grows the Locale always results in a real re-fetch of
`land_cover`, `hydrography`, `place_names`, `buildings`, and `roads`
together. They are fetched as one unit: a failure in any one of them leaves
all previous results untouched and marks the whole row `"failed"`, rather than
partially updating some of them. Note this now includes Trafikverket: a
missing or rejected `TRAFIKVERKET_TOKEN` fails the whole row, so the other
layers are not refreshed either until it is configured.

## States and error handling

| Backend result | Frontend behavior |
|---|---|
| `status: "missing"` | Treat like `"pending"` — show a loading/queued state, keep polling. |
| `status: "pending"` / `"running"` | Show a loading state; keep polling. |
| `status: "succeeded"` | Use `land_cover`, `hydrography`, `place_names`, `buildings`, `roads`, and `geometry`; stop polling. |
| `status: "failed"` | Show `error` in a retryable-looking state if useful, but there is no manual retry endpoint — the job only re-runs when the Locale is saved again. Stop polling. |
| `404` on the Locale itself | Normal "Locale not found or not yours" handling, same as any other `locales/{id}/...` action. |

## Out of scope

- Manually triggering or retrying a fetch from the frontend — there is no
  endpoint for this; only saving the Locale re-queues it.
- Changing `buffer_metres` per request — it is fixed server-side (5000 m)
  for the automatic per-Locale trigger.
- A sea-surface polygon in `hydrography` — Hydrografi has no such collection;
  sea surface is `land_cover`'s `"Hav"` objekttyp instead (see above).
- Lantmäteriet's official place-name register for the padded area — the
  `place_names` layer is OpenStreetMap; Ortnamn Direkt is only available
  through the point-based `place-names/` endpoints.
- Roads from Lantmäteriet — it has no live "Direkt"/API road product, only
  static downloadable vector datasets (Topografi 10/50 Nedladdning, vektor).
  Roads come from Trafikverket instead (see above).
