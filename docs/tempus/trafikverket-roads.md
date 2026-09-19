# Trafikverket: roads (NVDB)

Tempus fetches road segments for a Locale from Trafikverket's open API
(NVDB, object type `Vägnummer`). Unlike everything else in the Locale layers
this is **not Lantmäteriet** — a different provider with its own key and its
own request style. Nothing is stored beyond the per-Locale prefetch described
below; Trafikverket stays the source of truth.

## How the API differs from Lantmäteriet

- One endpoint, `POST https://api.trafikinfo.trafikverket.se/v2/data.json`,
  taking an XML body and returning JSON.
- The API key is **inside the request body** (`<LOGIN authenticationkey="..."/>`),
  not in an `Authorization` header, so `lantmateriet._authorization_header`
  is not used. Configuration is `TRAFIKVERKET_TOKEN`.
- Filtering is by **bbox only** (`WITHIN shape="box"`); there is no polygon
  search. Tempus therefore queries the geometry's bounding box and clips each
  segment to the exact geometry with Shapely afterwards, like
  `lantmateriet.land_cover_map`.

Verified against the live API (2026-09-18, with a real key):

| Finding | Detail |
|---|---|
| Box value format | `"lon lat, lon lat"` — comma-separated corners. `"lon lat lon lat"` is rejected (HTTP 400). |
| Geometry field name | Must include the dimension suffix: `Geometry.WKT-WGS84-3D`. The suffix is undocumented but required, in the filter and in `EXCLUDE`. |
| Paging | `limit` (tested up to 5000) and `skip`. |
| Response | All fields are returned when no `INCLUDE` is given. Tempus sends `EXCLUDE Geometry.WKT-SWEREF99TM-3D` to avoid transferring the geometry twice; all other fields are kept. |
| Validity | Rows carry `Valid_From`, `Valid_To` and `Deleted`. All sampled rows were current, but the client still filters. |
| Errors | Rejections come back as `{"ERROR": {"MESSAGE": ...}}` inside `RESULT` (a bad key gives `Invalid authentication`, a malformed box gives a parse message with HTTP 400). Tempus turns these into a clean error and never includes the key in it. |

## Endpoint

```text
GET /api/tempus/locales/{locale-id}/roads/
```

Returns current road segments clipped exactly to the Locale's geometry:

```json
{
  "locale": 42,
  "type": "FeatureCollection",
  "features": [
    {
      "collection": "Vägnummer",
      "feature_id": 8629229,
      "kind": "road",
      "properties": {
        "GID": 8629229, "Huvudnummer": 50, "Undernummer": 0,
        "Länstillhörighet": 20, "Europaväg": 0,
        "Element_Id": "13645:12425", "Start_Measure": 0.7379, "End_Measure": 1,
        "Seq_No": 101498, "Valid_From": "2023-09-29", "Valid_To": "9999-12-31",
        "Deleted": false, "...": "other upstream attributes"
      },
      "geometry": {"type": "LineString", "coordinates": [[15.4157, 60.4817], [15.4154, 60.4816]]}
    }
  ]
}
```

- `properties` is Trafikverket's record passed through **unchanged**, minus
  the `Geometry` block. Do not build UI on a renamed local schema.
- Geometry is converted from Trafikverket's WKT to GeoJSON, WGS 84,
  `[longitude, latitude]`, **2D** — elevation is dropped (the map layer has no
  use for it and it is a third of the coordinate payload). A segment leaving
  and re-entering the Locale becomes a `MultiLineString`.
- Only **currently valid** segments are returned: `Deleted` false and today's
  date within `[Valid_From, Valid_To)`. Historical versions are filtered out
  before anything is stored or returned.
- Segments are deduplicated by `GID`.

Status codes match the other Locale layers: `503` when `TRAFIKVERKET_TOKEN` is
missing, `413` when the area holds more than `TRAFIKVERKET_MAX_FEATURES`
segments (the request fails rather than returning a partial layer), `429`
when rate limited, `502` on any other upstream failure.

## Calling it from the frontend

The frontend makes **one combined call** that returns every layer — land
cover, hydrography, place names, buildings and roads — instead of one call per
layer:

```http
GET /api/tempus/locales/{localeId}/land-cover/fetch/
```

The full request, the polling loop, the `status` values and the error
handling for that call are in
[land-cover-fetch-handoff.md](land-cover-fetch-handoff.md#calling-it-from-the-frontend).
This section only covers what is specific to the `roads` key in the response.

The frontend never talks to Trafikverket and never holds a Trafikverket key —
that lives only in the backend's `TRAFIKVERKET_TOKEN`.

`GET /locales/{id}/roads/` (above) is a single-layer, synchronous alternative
clipped exactly to the Locale. The combined call does not need it; use it only
if a view really wants roads alone.

### The `roads` value

Once `status === "succeeded"`, `roads` is a GeoJSON `FeatureCollection` with
the same feature shape as the endpoint example above. It covers the Locale's
bounding box **padded 5 km**, like every other layer in this response, and is
**not** clipped to the Locale's own shape. Render `features` directly as a
GeoJSON source — every geometry is already WGS 84 `[longitude, latitude]`, so
no client-side reprojection is needed. An empty `features` array is a valid
result (no numbered roads in the area), not an error.

- `geometry.type` is `LineString`, or `MultiLineString` where one segment
  leaves and re-enters the Locale. Handle both.
- `kind` is always `"road"`. Keep unknown `kind` values renderable, in case
  more road types are added later.
- `properties` is Trafikverket's own record. `Huvudnummer`/`Undernummer` give
  the road number and are the natural label. Treat the other fields
  (`Europaväg`, `Länstillhörighet`, `Start_Measure`, ...) as opaque unless you
  have confirmed what a value means — do not hard-code an enum from them.
- `feature_id` (the upstream `GID`) is unique within one response, since
  Tempus deduplicates by it, so it works as a key for a map layer. Whether a
  `GID` stays the same across Trafikverket data updates is not verified, so
  don't persist it on the client as a long-lived identifier.

### Roads-specific failures in the combined call

A Trafikverket problem does not show up as an HTTP error on the combined call
(it always answers `200`); it makes the whole row `status: "failed"` with an
`error` message, and **no layer is refreshed** — see "Persisted prefetch"
below. So the frontend handles it exactly like any other failed fetch. The
`error` text for the roads-specific causes is one of: `Configure
TRAFIKVERKET_TOKEN (and optionally TRAFIKVERKET_URL).`, `The requested area
contains too many road segments; choose a smaller area.`, `Trafikverket
rejected the query: ...`, `Trafikverket is rate limiting requests.`, or
`Could not reach Trafikverket.` — show it behind a generic wrapper, don't
depend on the wording.

The per-status table (`413`, `429`, `502`, `503`, ...) applies only to the
single-layer `GET /locales/{id}/roads/`, where those become real HTTP status
codes.

## Persisted prefetch

Roads are one of the sources in `tempus/services/locale_sources.py`, so they
are also fetched with the Locale's 5 km padded area and stored in
`LandCoverFetch.roads`, exposed as `roads` in
`GET /locales/{id}/land-cover/fetch/` — see
[land-cover-fetch-handoff.md](land-cover-fetch-handoff.md).

**The prefetch is all-or-nothing across every source.** A missing or invalid
`TRAFIKVERKET_TOKEN` now fails the whole row, so land cover, hydrography,
place names and buildings are not refreshed either until it is configured.
Set the key in every environment where the Locale prefetch runs.

Adding the `roads` field needs a migration (`LandCoverFetch.roads`).

## Configuration

```env
TRAFIKVERKET_TOKEN=<API key from Trafikverket>
TRAFIKVERKET_URL=https://api.trafikinfo.trafikverket.se/v2/data.json
TRAFIKVERKET_TIMEOUT=30
TRAFIKVERKET_CACHE_SECONDS=2592000
TRAFIKVERKET_PAGE_SIZE=1000
TRAFIKVERKET_MAX_FEATURES=20000
```

Responses are cached per exact geometry (default 30 days) and concurrent
identical requests are coalesced, the same way as the Lantmäteriet layers.

## Not verified

- Behaviour at Trafikverket's own maximum `limit` and its rate-limit response
  body (a `429` is mapped to a rate-limit error, but was not observed).
- Whether `MAX_FEATURES=20000` is a sensible cap for a large Locale — it is a
  Tempus safety limit, not a Trafikverket one. Watch for `413` on big areas.
- Only object type `Vägnummer` is queried. Whether that covers roads without
  a road number (local and municipal roads) was not checked — inspect a
  Locale in a rural area before assuming the layer is a complete road map.

## Implementation boundary

- Client: `tempus/services/trafikverket.py` (`roads_in_geometry`)
- Live action: `tempus/views/reference.py` (`LocaleViewSet.roads`)
- Prefetch: `tempus/services/locale_sources.py` (`SOURCES`),
  `tempus/models/land_cover.py` (`LandCoverFetch.roads`)
- Configuration: `origo/settings.py` (`TRAFIKVERKET_API`), `.env.example`
