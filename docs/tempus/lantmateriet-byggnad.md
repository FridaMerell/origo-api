# Lantmäteriet: Byggnad Direkt (buildings)

> **Not in use.** Buildings for Locales now come from OpenStreetMap — see
> [openstreetmap-buildings.md](openstreetmap-buildings.md). Byggnad Direkt is
> the full building register and needs a legal review before access is
> granted; without it every call fails with HTTP 403 ("Scope validation
> failed"), which stopped the whole Locale prefetch. The client code
> (`lantmateriet.buildings_in_geometry` and its tiling helpers) is still in
> `tempus/services/lantmateriet.py` but is not registered in `SOURCES` and no
> endpoint calls it. The text below describes that unused integration.

Tempus can look up Lantmäteriet's building register ("Byggnad Direkt") for a
Locale, and — unlike Ortnamn Direkt — get an exact server-side clip to an
arbitrary geometry, not just a nearest-point lookup. The upstream service is
authoritative; Tempus does not store a copy of the register beyond the
background-prefetch cache described below.

## Not the same kind of API as Marktäcke/Hydrografi/Administrativa gränser

Byggnad Direkt is, like Ortnamn Direkt, a separate Lantmäteriet REST API
(`distribution/produkter/byggnad/v3`), not OGC API Features. Confirmed
reachable at that base URL (the gateway returns its own "Missing
Credentials" error unauthenticated, not a 404).

Unlike Ortnamn, it **does** accept an arbitrary search geometry:
`POST /referens/geometri` takes a GeoJSON/GML polygon (plus an optional
metre buffer) and returns buildings intersecting it — the same
clip-to-geometry shape as `land-cover/map/`, just via a different transport.
The documented per-request limits are a max polygon area of **1,000,000 m²**
and a max perimeter of **200,000 m**. A Locale (or its 5 km padded
background-fetch area) larger than that is automatically **tiled**
client-side into smaller geometries, queried separately, and merged/deduped
by building id — see `tempus.services.lantmateriet.buildings_in_geometry`.
This means `buildings/` is an exact clip like `land-cover/map/`, not an
approximation like `place-names/search/`.

## Endpoints

```text
GET /api/tempus/locales/{locale-id}/buildings/
```

Returns every Byggnad Direkt building feature clipped exactly to this
Locale's `MultiPolygon` (tiled internally if the Locale is large — see
above). `413` if the Locale needs more tiles than the configured safety
limit (`LANTMATERIET_BYGGNAD_MAX_TILES`, default 400 — this is a Tempus
safety limit, not a Lantmäteriet one); `502` on upstream failure; `503` when
the integration lacks configuration.

```json
{
  "locale": 42,
  "type": "FeatureCollection",
  "features": [
    {
      "id": "<upstream identity>",
      "properties": {"...": "upstream attributes, passed through unchanged"},
      "geometry": {"type": "Polygon", "coordinates": []}
    }
  ]
}
```

Building features are passed through **unchanged** — no field renaming or
reshaping like `place_names_search` does for Ortnamn. This is not a stylistic
choice: Geotorget's technical description for this product does not specify
building attribute field names (purpose/ändamål, name, floor count, area,
...), so there is nothing confirmed to reshape against. Treat `properties`
the same way `land_cover_map`'s `properties.objekttyp` is treated — the raw
source of truth, not something to hard-code a local enum from.

## Persisted background fetch (padded area, like land cover)

Buildings are also included in the existing background prefetch that runs
whenever a Locale is created or its geometry changes — the same
`LandCoverFetch` row used by `land-cover/fetch/` and `place_names` (see
[lantmateriet-ortnamn.md](lantmateriet-ortnamn.md) and
[land-cover-fetch-handoff.md](land-cover-fetch-handoff.md)), padded 5 km
around the Locale's bounding box and stored permanently until the next
re-fetch. Its `buildings` field is populated by padding the Locale's
geometry (`tempus.services.lantmateriet.buffered_bbox`, shared with the
other three sources in the same background run — see
`tempus.tasks.fetch_locale_land_cover`) and calling `buildings_in_geometry`
on the result, which tiles internally exactly like the live endpoint above
— this one IS a genuine exact clip of the full padded area, not the
grid-sampled
approximation `place_names` is.

This requires the same **database migration** already flagged in
lantmateriet-ortnamn.md for `place_names` — `buildings` was added to
`LandCoverFetch` in the same, still-unapplied change. Run
`manage.py makemigrations tempus` and `migrate` yourselves before either
field reaches the database.

## Authentication and configuration

Falls back to the same Marktäcke Basic-auth/access-token credentials
(`LANTMATERIET_MARKTACKE_*`) unless its own `LANTMATERIET_BYGGNAD_*` values
are set — **verify live whether this product needs its own API Portal
subscription/key** rather than assuming the shared Geotorget account covers
it automatically.

```env
LANTMATERIET_BYGGNAD_BASE_URL=https://api.lantmateriet.se/distribution/produkter/byggnad/v3
LANTMATERIET_BYGGNAD_USERNAME=<Geotorget username, or leave unset to reuse Marktäcke's>
LANTMATERIET_BYGGNAD_PASSWORD=<Geotorget password, or leave unset to reuse Marktäcke's>
LANTMATERIET_BYGGNAD_TIMEOUT=15
LANTMATERIET_BYGGNAD_CACHE_SECONDS=2592000
LANTMATERIET_BYGGNAD_MAX_AREA_SQM=1000000
LANTMATERIET_BYGGNAD_MAX_PERIMETER_M=200000
LANTMATERIET_BYGGNAD_MAX_TILES=400
```

`MAX_AREA_SQM`/`MAX_PERIMETER_M` mirror Lantmäteriet's own documented
per-request limits — only change them if Lantmäteriet's documentation
changes, not as a general performance knob. `MAX_TILES` is purely a Tempus
safety cap on how many upstream requests one fetch may issue.

## Access is a separate order (403 until granted)

Tested 2026-09-18 with the Basic credentials that work for Marktäcke and
Ortnamn: both `GET /health` and `POST /referens/geometri` answer **HTTP 403**
(`900910 "The access token does not allow you to access the requested
resource"`, `Scope validation failed`). The credentials are valid — this is
the API gateway saying the account has no authorization for **this product**.

On Geotorget, Byggnad Direkt is marked "Juridisk prövning: Ja" and carries
"Användningsvillkor för värdefulla datamängder som innehåller
personuppgifter", i.e. it has to be ordered and legally assessed before
access is granted; having Ortnamn or Marktäcke does not cover it. Until it is
granted, `buildings_in_geometry` fails with `Lantmäteriet Byggnad Direkt
returned HTTP 403.` and — because the Locale prefetch is all-or-nothing —
that failure stops **every** layer from being refreshed. See
[land-cover-fetch-handoff.md](land-cover-fetch-handoff.md).

## What has not been verified live

Only the base URL and path are confirmed reachable (see above) — no
successful authenticated response has been seen yet, because of the 403
above.

- Confirm the actual building attribute field names in `properties` before
  building any UI around them — none are documented upstream, so the client
  passes features through unchanged (see "Endpoints" above) rather than
  guessing a schema.
- Confirm whether `POST /referens/geometri` returns a plain GeoJSON
  `FeatureCollection` with a top-level `features` array, matching the
  parsing in `buildings_in_geometry` — Geotorget's documentation says
  "GeoJSON or GML FeatureCollection" but does not show a worked JSON example.
- Confirm the 1,000,000 m² / 200,000 m per-request limits are still current
  and apply to this endpoint specifically, not just the batch ID endpoints.
- (Answered: it does need its own authorization — see the 403 section above.
  Whether the same Basic credentials work once it is granted is still to be
  confirmed.)

## Implementation boundary

- HTTP client: `tempus/services/lantmateriet.py` (Byggnad Direkt section:
  `buildings_in_geometry`; padded-area fetches go through the shared
  `map_for_area` helper rather than a dedicated per-source wrapper)
- Live Locale action: `tempus/views/reference.py`
  (`LocaleViewSet.buildings`)
- Persisted background fetch: `tempus/tasks.py` (`fetch_locale_land_cover`),
  `tempus/signals.py` (`prefetch_locale_land_cover`),
  `tempus/models/land_cover.py` (`LandCoverFetch.buildings`), exposed via
  `LocaleViewSet.land_cover_fetch` — see
  [land-cover-fetch-handoff.md](land-cover-fetch-handoff.md)
- Configuration: `origo/settings.py` (`LANTMATERIET_BYGGNAD`)
- Environment-variable reference: `.env.example`
