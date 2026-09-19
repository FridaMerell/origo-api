# Lantmäteriet: Ortnamn Direkt (place names)

Tempus can look up Lantmäteriet's official place names ("ortnamn") near a
point inside a Locale, and search them by name, county, or municipality
within a Locale. The upstream service is authoritative; Tempus does not store
a copy of the register.

## Not the same kind of API as Marktäcke/Hydrografi/Administrativa gränser

Those three products are OGC API Features services (`ogc-features/v1/...`),
queried by `bbox` and clipped exactly to a Locale's geometry server-side (see
[lantmateriet-marktacke.md](lantmateriet-marktacke.md)). **Ortnamn Direkt is
a different, older Lantmäteriet REST API** (`distribution/produkter/ortnamn/v2.2`)
with its own request/response shape.

**Use v2.2.** It is the current version (Geotorget's "Åtkomstpunkt"). The
earlier default, v2.1, is the outgoing version and answers **HTTP 401** to an
account authorized for the current one — the same credentials that get `200`
on v2.2. A `401` from Ortnamn is therefore first a base-URL/version question,
not necessarily a credentials one.

**SWEREF 99 only.** Ortnamn Direkt accepts and returns only SWEREF 99
reference systems: `srid=4326` and `punktSrid=4326` are rejected with `400
Reference system not supported: 4326`. Tempus talks EPSG:3006 to the API and
converts every point to and from WGS 84 itself
(`tempus/services/geo.py`: `wgs84_to_sweref99tm`, `sweref99tm_to_wgs84`,
checked against 895 real coordinate pairs to within 0.01 mm), so everything
Tempus returns is still WGS 84 `[longitude, latitude]`.

Most importantly, **it has no bbox or radius search**. `punkt` returns only
the single closest name to a point, not every name within a distance or
area. There is therefore no per-viewport "place names map layer" endpoint
like `land-cover/?bbox=...` — only:

- a nearest-point lookup, scoped to one Locale, and
- a name/county/municipality search, filtered after the fact to points that
  fall inside one Locale's geometry (Tempus does this filtering itself;
  Lantmäteriet cannot clip for it).

## Endpoints

```text
GET /api/tempus/locales/{locale-id}/place-names/?longitude={longitude}&latitude={latitude}
```

Returns the single closest Ortnamn Direkt place name to a WGS 84 point. The
point must be inside the Locale's `MultiPolygon`, same rule as
`land-cover/`. `404` when Lantmäteriet has no name for the request; `502` on
upstream failure; `503` when the integration lacks configuration.

```json
{
  "locale": 42,
  "point": {"type": "Point", "coordinates": [18.0649, 59.3293]},
  "place_name": {
    "id": "<upstream identity>",
    "namn": "Björkhaga",
    "sprak": "Svenska",
    "namntyp": "Bebyggelse",
    "lankod": "01",
    "lannamn": "Stockholms län",
    "kommunkod": "0180",
    "kommunnamn": "Stockholm",
    "geometry": {"type": "Point", "coordinates": [18.0649, 59.3293]}
  }
}
```

```text
GET /api/tempus/locales/{locale-id}/place-names/search/?namn={text}&match=contains
GET /api/tempus/locales/{locale-id}/place-names/search/?kommunkod={code}
GET /api/tempus/locales/{locale-id}/place-names/search/?lankod={code}
```

At least one of `namn`, `lankod`, or `kommunkod` is required. Optional
`match` (`startsWith`/`equals`/`endsWith`/`contains`), `namntyp` (comma-
separated, see below), and `maxHits` (default 100, upstream max 400 — there
is no offset/pagination parameter on this endpoint yet). Returns every
upstream match whose point falls inside the Locale's geometry:

```json
{
  "locale": 42,
  "total_upstream": 3,
  "features": [
    {
      "id": "<upstream identity>",
      "namn": "Björkhaga",
      "sprak": "Svenska",
      "namntyp": "Bebyggelse",
      "lankod": "01",
      "lannamn": "Stockholms län",
      "kommunkod": "0180",
      "kommunnamn": "Stockholm",
      "geometry": {"type": "Point", "coordinates": [18.0649, 59.3293]}
    }
  ]
}
```

`total_upstream` is Lantmäteriet's own match count *before* the Locale-
boundary filter, so it can be larger than `features.length` — do not treat
it as the number of results returned.

## Not used for the Locale prefetch

The Locale's background prefetch (`LandCoverFetch.place_names`, exposed in
`land-cover/fetch/`) does **not** use Ortnamn Direkt. Because the API cannot
be queried by area, the only ways to cover an area were:

- a **grid of nearest-point lookups** — used first, and dropped: a fixed
  10 × 10 = 100 requests (about 31 s measured, one request per name found)
  regardless of the Locale's size, and still incomplete, since each request
  returns a single name; or
- **listing whole municipalities** — the API demands a search term, so a
  municipality is only listable by splitting on `namn` with `match=startsWith`
  one letter at a time: measured for one rural municipality at 30 requests
  and 56 s for its 3 951 names, to use a few hundred of them.

Place names for the prefetch now come from OpenStreetMap: one Overpass query
for the padded area returns every named village, hamlet, farm and locality in
it. See [openstreetmap-buildings.md](openstreetmap-buildings.md#place-names).
The trade-off is that OSM is not Lantmäteriet's authoritative register for
spelling; Ortnamn Direkt remains the source for the two point-based Locale
endpoints above (`place-names/` and `place-names/search/`).

## Name types (`namntyp`)

`Anläggning`, `Bebyggelse`, `Tätort`, `Glaciär`, `Fornlämning`, `Kyrka`,
`Naturvårdsområde`, `Sankmark`, `Natur- och terrängnamn`, `Trakt`,
`Vattendelsområde`, `Vattendrag`, `Hav och sjö` (`ORTNAMN_NAMNTYPER` in
`tempus/services/lantmateriet.py`).

There is no dedicated "gårdsnamn" (farm name) category. An individual farm,
if Lantmäteriet's place-name authority has registered and located it, would
appear under `namntyp: "Bebyggelse"` alongside villages and other
settlements — **this has not been verified against a real, authenticated
response**. Whether farm-level names are actually present (versus only
larger settlements) is a property of Lantmäteriet's register, not something
this integration controls; check a live `place-names/search/` response for a
known farm name before relying on it.

## Authentication and configuration

Falls back to the same Marktäcke Basic-auth/access-token credentials
(`LANTMATERIET_MARKTACKE_*`) unless its own `LANTMATERIET_ORTNAMN_*` values
are set. Confirmed live: the shared Basic credentials are accepted on v2.2
once the account is authorized for the Ortnamn Direkt product. If your `.env`
still sets `LANTMATERIET_ORTNAMN_BASE_URL` to a v2.1 URL, update or remove it.

```env
LANTMATERIET_ORTNAMN_BASE_URL=https://api.lantmateriet.se/distribution/produkter/ortnamn/v2.2
LANTMATERIET_ORTNAMN_USERNAME=<Geotorget username, or leave unset to reuse Marktäcke's>
LANTMATERIET_ORTNAMN_PASSWORD=<Geotorget password, or leave unset to reuse Marktäcke's>
LANTMATERIET_ORTNAMN_TIMEOUT=15
LANTMATERIET_ORTNAMN_CACHE_SECONDS=2592000
```

## Verified live (2026-09-18) and what is not

Checked against the real v2.2 API with real credentials. These earlier
assumptions from Geotorget's documentation turned out to be **wrong** and were
fixed:

| Assumed | Actual |
|---|---|
| Base path `.../ortnamn/v2.1` | v2.2 is current; v2.1 answers 401 |
| `srid=4326` gives WGS 84 | Rejected (400); only SWEREF 99 (EPSG:3006–3018) |
| `punkt` as `lat,lon` with `punktSrid=4326` | `northing,easting` with `punktSrid=3006` |
| `maxHits` can be sent with `punkt` | Rejected (400 "maxHits is not allowed with punkt") |
| Fields on the feature (`features[].namn`, `.placering`) | Everything is under `features[].properties`; `geometry` is `null` |
| `punkt` in one of several shapes | A GeoJSON `Point` in the requested SRID |

Also observed: one name usually has several placements (`placering[]` —
"Stockholm" returns three), so Tempus returns one feature per (name,
placement) pair, and `place-names/` picks the placement closest to the query
point.

Still not verified:

- Whether farm-level (`Bebyggelse`) names are present in practice (see "Name
  types" above).
- The `namntyp` filter values and `match` behaviour beyond what the technical
  description states.

## Implementation boundary

- HTTP client: `tempus/services/lantmateriet.py` (Ortnamn section:
  `place_names_search`, `place_name_nearest`)
- Live Locale actions: `tempus/views/reference.py` (`LocaleViewSet.place_names`,
  `LocaleViewSet.place_names_search`)
- The persisted prefetch (`LandCoverFetch.place_names`) does not use this
  client any more — see "Not used for the Locale prefetch" above.
- Configuration: `origo/settings.py` (`LANTMATERIET_ORTNAMN`)
- Environment-variable reference: `.env.example`

Buildings (Byggnad Direkt) are a sibling non-OGC-Features product on the
same Locale endpoints, but unlike Ortnamn it supports an exact geometry
clip — see [lantmateriet-byggnad.md](lantmateriet-byggnad.md).
