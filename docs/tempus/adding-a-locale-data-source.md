# Adding a new Locale data source

This is the checklist for wiring a new external data source into a Locale —
whether that's another Lantmäteriet product or something else entirely (a
different provider, an open dataset, an internal service). It's written from
the three integrations that already exist, which cover the three shapes a
new source is likely to take. Skim their code before starting; copying the
closest-matching one is faster than working from this checklist alone.

## Pick your shape first

| Your source... | Closest existing example | Pattern |
|---|---|---|
| Is a real OGC API Features service (`/collections/{id}/items?bbox=...`) | Marktäcke Direkt — [lantmateriet-marktacke.md](lantmateriet-marktacke.md), `tempus/services/lantmateriet.py`'s `land_cover_map`/`land_cover_in_bbox` | Query by `bbox`, page through results, Shapely-clip to the exact Locale geometry server-side |
| Accepts an arbitrary search geometry (a polygon in the request body), but caps request size | Byggnad Direkt — [lantmateriet-byggnad.md](lantmateriet-byggnad.md), `buildings_in_geometry` | Same exact-clip result as above, but tile the geometry client-side into chunks under the provider's own area/perimeter limit, then merge + dedup by id |
| Only supports point lookup, free-text search, or some other narrow query — no bbox/polygon at all | Ortnamn Direkt — [lantmateriet-ortnamn.md](lantmateriet-ortnamn.md#not-used-for-the-locale-prefetch) | **Don't use it for the area prefetch.** We tried a grid of point lookups (100 requests, 31 s, one request per name, still incomplete) and listing a whole municipality (30 requests, 56 s, 3 951 names to use a few hundred) — both were wrong. Take the layer from a source that can query by area (place names now come from OpenStreetMap, one request), and keep the narrow API only for point endpoints. |

If you're not sure which bucket a new source falls into, that's the first
thing to find out live (see "Verify before you build" below) — the shape of
the upstream API determines almost everything else here, not the other way
around.

## Saving what you get back: normalising geometry

Every source so far (Marktäcke, Hydrografi, Administrativa gränser, Ortnamn,
Byggnad) happens to return coordinates as plain GeoJSON already, in WGS 84.
Not every provider will — Trafikverket's road data (NVDB-based), for
example, returns geometry as **WKT strings**, often in two projections at
once:

```json
"Geometry": {
  "WKT-SWEREF99TM-3D": "LINESTRING Z (522847.81 6705131.93 135.0, ...)",
  "WKT-WGS84-3D": "LINESTRING Z (15.4156 60.4817 135.0, ...)"
}
```

Convert this to GeoJSON **before** it goes anywhere near a `JSONField`,
rather than storing raw WKT and converting on every read. This project's
convention — stated explicitly in `tempus/services/geo.py`'s module
docstring — is GeoJSON, `[longitude, latitude]`, WGS 84, everywhere data is
stored or returned over the API. Breaking that convention for one source
means every consumer (frontend, admin, future code) has to special-case it.

Concretely:

1. **Prefer the WGS 84 variant if the source gives you one directly**
   (`WKT-WGS84-3D` above) rather than reprojecting SWEREF 99 TM yourself —
   less that can go wrong, and it's already what this project stores
   everywhere else. Only reproject when a source gives you just one
   projection and it isn't WGS 84 (`pyproj` is the standard tool for that;
   it isn't currently a project dependency, so check with whoever owns
   `requirements.txt` before adding it).
2. **Parse WKT with Shapely**, already a dependency and already used
   throughout `lantmateriet.py`:
   ```python
   from shapely import wkt
   from shapely.geometry import mapping

   geojson_geometry = mapping(wkt.loads(wkt_string))
   ```
   `mapping()` preserves a 3D `LINESTRING Z`'s elevation values as a third
   coordinate (`[lon, lat, elevation]`) — GeoJSON supports that natively, no
   extra handling needed, but decide up front whether elevation is actually
   useful to keep or just noise to drop.
3. **Filter validity/soft-deletion before storing, not after.** NVDB-style
   sources commonly version their data with `Valid_From`/`Valid_To` and a
   `Deleted` flag rather than actually removing old rows — storing every
   historical version of every segment inside a Locale's padded area is
   rarely what you want. Filter to the currently-valid set (`Deleted is
   False` and today's date inside `[Valid_From, Valid_To)`) in the client
   function itself, the same way `_is_wetland` classifies features before
   they're returned rather than leaving that to callers.
4. **Decide what to keep from the rest of the record deliberately, not
   reflexively.** A road segment like the one above carries linear-
   referencing fields (`Start_Measure`/`End_Measure`, `Seq_No`, `Role`,
   `Direction`, `IsHost`) that describe *where on a larger road* this
   segment sits, not just its own geometry — useful if you need to
   reconstruct a continuous route, probably noise if you just want "roads
   that pass through this Locale" for a map layer. Match Byggnad Direkt's
   approach (pass upstream properties through unchanged when the schema
   isn't yours to redesign) rather than inventing a reshaped field set
   nobody asked for.
5. **Store the result the same shape as everything else**: a GeoJSON
   `Feature`/`FeatureCollection` with a real `geometry` key, so it renders
   with the same frontend code path as land cover, buildings, etc. — not a
   bespoke shape just because the upstream source's was different.

## The full checklist

Assume a source named `Foo` throughout.

1. **Client code** — `tempus/services/<provider>.py` (reuse
   `tempus/services/lantmateriet.py` if it's another Lantmäteriet product;
   otherwise create a new service module). Needs, at minimum:
   - A `_foo_config()` reading `getattr(settings, "FOO", {})`
   - Auth handling. If it's Basic auth or a static bearer token, copy
     `_authorization_header()` (already parameterised by a config dict — you
     can usually call it directly with your own config) rather than
     reinventing it. It no longer has an OAuth2 client-credentials branch
     (removed 2026-09-17: never exercised against a real token endpoint, and
     its cache key was hardcoded/shared across products) — if your source
     genuinely needs OAuth client-credentials, build it deliberately, verify
     it against the source's real token endpoint, and give it its own cache
     key rather than reusing a Lantmäteriet-shaped one.
   - The actual fetch function(s), wrapped in `_cache_singleflight` (already
     in `lantmateriet.py`, or copy it) so concurrent identical requests
     don't all hit the upstream API and each other's rate limits at once.
   - Raise the existing `LantmaterietConfigurationError`/
     `LantmaterietAPIError`/`LantmaterietMapTooLargeError`/
     `LantmaterietRateLimitedError` (or your own equivalents for a
     non-Lantmäteriet source) — the view layer already knows how to turn
     these into `503`/`502`/`413`/`429`.
2. **Settings block** — `origo/settings.py`, right next to the other
   `LANTMATERIET_*` blocks if it's Lantmäteriet, otherwise wherever makes
   sense. Include `BASE_URL`, credentials (falling back to Marktäcke's if
   it's the same Geotorget account — verify this live, see below),
   `TIMEOUT`, `CACHE_SECONDS`, and any provider-specific safety limits (area
   caps, max tiles, max grid points — whatever stops one Locale from issuing
   an unbounded number of upstream requests).
3. **`.env.example`** — one commented block mirroring the settings block,
   with a one-paragraph comment explaining what makes this source different
   from the others (OGC Features vs. REST, exact vs. approximated, shared
   vs. separate product authorization).
4. **Live Locale action** — `tempus/views/reference.py`, a new
   `@action(detail=True, methods=["get"], url_path="foo")` method on
   `LocaleViewSet`, following the existing `land_cover`/`buildings`/
   `place_names` actions: resolve the Locale, call your service function,
   catch the four `Lantmateriet*Error` types into the matching status codes,
   return `{"locale": locale.pk, **result}`.
5. **Persisted background fetch (only if you want it permanent, not just
   live)** — this is the part that's easy to skip and shouldn't be:
   - Add a field to `LandCoverFetch` in `tempus/models/land_cover.py`
     (`foo = models.JSONField(default=dict, blank=True)`) — despite the
     model's name, it's the shared "padded-area background fetch" row for
     every source, not just land cover.
   - Register it in `SOURCES` in `tempus/services/locale_sources.py`: one
     `LocaleSource(key=..., field=..., label=..., fetch=lambda geometry,
     bbox: ...)` entry. `fetch` receives the padded GeoJSON geometry and the
     padded bbox tuple (computed once, shared by every source) and returns
     a FeatureCollection. That single entry is all the wiring there is:
     `fetch_locale_land_cover` (`tempus/tasks.py`), the
     `land-cover/fetch/` response (`LocaleViewSet.land_cover_fetch`) and
     `LandCoverFetchAdmin` all loop over `SOURCES`, so none of them need
     editing. The task still treats all sources as **one atomic unit** — if
     any fetch fails, no field (yours or the others') is overwritten.
   - `tempus/signals.py` already triggers the task on every Locale
     `post_save` — no new signal needed.
   - This needs a migration for the new field. Make the model change; that's
     as far as you take it — `makemigrations`/`migrate` is yours to run.
6. **Admin visibility** — a source registered in `SOURCES` shows up in
   `LandCoverFetchAdmin` automatically (feature count in the list column,
   raw JSON in the collapsed "Rådata" fieldset). A brand-new model (not a
   `LandCoverFetch` field) needs its own `@admin.register(..., site=site)`
   class.
7. **Docs** — a new `docs/tempus/lantmateriet-<name>.md` (or
   `<provider>-<name>.md`) following the shape of the three existing ones:
   what the upstream API actually is (OGC Features vs. REST, exact vs.
   approximated), the endpoint(s) and example JSON, the persisted-fetch
   section if you added one, an explicit "what has not been verified live"
   section (see below), and an "Implementation boundary" file list at the
   end. Link it from `docs/tempus/README.md`'s index and from
   `docs/tempus/api.md`'s `locales/` row.

## The source registry

`tempus/services/locale_sources.py` holds `SOURCES`, an ordered tuple of
`LocaleSource` entries — one per external source prefetched for a Locale's
padded (5 km) area. It exists so that adding a source is one entry instead
of edits in the task, the view and the admin.

```python
@dataclass(frozen=True)
class LocaleSource:
    key: str      # name in the land-cover/fetch/ JSON response
    field: str    # LandCoverFetch model field the result is stored in
    label: str    # human-readable name, shown in the admin list column
    fetch: Callable[[dict, tuple], dict]   # (padded_geometry, padded_bbox) -> FeatureCollection
```

`key` and `field` differ only where history made them differ: land cover is
stored in the field `result` but exposed as `land_cover`.

### What reads it

| Consumer | What it does with `SOURCES` |
|---|---|
| `tasks.fetch_locale_land_cover` | Computes the padded geometry/bbox **once**, calls every `source.fetch(geometry, bbox)`, and stores each result in `source.field`. If any fetch raises, nothing is saved (previous results stay), and the row is marked `failed`. |
| `LocaleViewSet.land_cover_fetch` | Adds `payload[source.key] = getattr(fetch, source.field)` for every source when the fetch succeeded. |
| `LandCoverFetchAdmin` | Shows "Label: count" per source in one list column and puts every `source.field` in the collapsed "Rådata" fieldset. |

### What `fetch` receives

Both a geometry and a bbox are passed to every source, so a source can take
whichever its client function needs. Every current source takes the padded
**geometry** and ignores the bbox (a source that is queried by bbox only can
use the bbox tuple instead) — that's why the existing entries are lambdas:

```python
LocaleSource(
    key="place_names",
    field="place_names",
    label="Place names",
    fetch=lambda geometry, bbox: openstreetmap.place_names_in_geometry(geometry),
),
```

### Worked example: adding roads

This is exactly how roads were added — the real implementation is
`trafikverket.roads_in_geometry(geometry)` in
`tempus/services/trafikverket.py` (see [trafikverket-roads.md](trafikverket-roads.md)),
returning a GeoJSON `FeatureCollection` (see "Saving what you get back" above
for the WKT conversion and validity filtering it performs). Its error classes
subclass the `Lantmateriet*` ones, which is what makes step 3 below "just
work" in the task and the view.

1. Model — add the field to `LandCoverFetch` in
   `tempus/models/land_cover.py` (this is the step that needs a migration):
   ```python
   roads = models.JSONField(default=dict, blank=True)
   ```
2. Registry — add one entry to `SOURCES`:
   ```python
   from tempus.services import lantmateriet, trafikverket

   LocaleSource(
       key="roads",
       field="roads",
       label="Roads",
       fetch=lambda geometry, bbox: trafikverket.roads_in_geometry(geometry),
   ),
   ```
3. Errors — the task catches `LantmaterietConfigurationError` and
   `LantmaterietAPIError` (and any other exception, which marks the row
   failed and re-raises). If your client raises its own error types they
   still fail the fetch safely via the generic handler, but the row's
   `error` message will read `ClassName: message` instead of a clean
   message; subclass `LantmaterietAPIError` (or extend the `except` tuple in
   `tasks.py`) if you want the clean form.

That's everything for the prefetch path. The response gains a `roads` key,
the admin gains "Roads: N" in the list column and a `roads` field in the raw
fieldset, and nothing else is edited. Also do the non-registry steps from the
checklist that still apply: settings block, `.env.example`, docs, and a live
`@action` on `LocaleViewSet` if you want a non-prefetched endpoint.

### What the registry does not do

- It does not create the model field or the migration — those stay explicit.
- It covers only the padded-area **prefetch**. A live per-Locale endpoint
  (like `LocaleViewSet.buildings`) is still its own `@action`.
- It does not make a point-only upstream (like Ortnamn Direkt) usable for an
  area. Faking area coverage with many point requests was tried and removed —
  see the table at the top.
- Order in `SOURCES` is the order of the admin column and of the fetch
  calls; the fetches run sequentially, so a slow source delays the rest.

## Verify before you build

This codebase has a hard rule (see the top-level working agreement) about
not presenting unverified assumptions about an external API as working
code. In practice, for a new Locale data source, that means:

- **Before writing the client**: hit the base URL/health endpoint
  unauthenticated (browser or `curl`) and confirm it's reachable and returns
  the auth-error shape you expect, not a 404. This alone catches a wrong
  base URL or product path before any code depends on it.
- **Before claiming a field schema is correct**: if you can get a real
  authenticated response (even one row), check it against whatever you
  wrote in the client. If you can't (no credentials yet, like Ortnamn/
  Byggnad when they were built), say so explicitly in the doc's "what has
  not been verified live" section rather than presenting the field names as
  confirmed — see how `lantmateriet-ortnamn.md` and `lantmateriet-byggnad.md`
  do this.
- **Before assuming shared credentials work**: Hydrografi and Administrativa
  gränser are confirmed to reuse the Marktäcke Geotorget account; Ortnamn
  and Byggnad are *not* confirmed either way (different API family
  entirely — `distribution/produkter/...` vs `ogc-features/v1/...`) and
  fall back to Marktäcke's credentials as a guess, flagged as unverified.
  Each new product typically needs its own authorization requested on
  Geotorget even on the same account, so check this explicitly rather than
  assuming a shared login covers everything.
- **Test the client function standalone** before wiring it into a view: a
  minimal `django.conf.settings.configure(...)` + `django.setup()` script
  with `requests.get`/`.post` monkeypatched to return a synthetic response
  is enough to prove your parameter-building and response-parsing logic
  works, without needing a live server, database, or real credentials. See
  the pattern in this session's own scratch tests if you want a template —
  ask and it can be pointed out.

## Things to not repeat

- Don't build an area layer on top of an API that can't be queried by area.
  Ortnamn Direkt can't, and the two workarounds tried (a grid of nearest-point
  lookups, then listing a whole municipality by first letter) cost 100 and 30
  requests respectively for a few km² of interest. Check the upstream API's
  actual capabilities first; if it has no area query, use a different source
  for the layer. Also count the requests a Locale will cost before shipping:
  the number of calls should follow from the size of the area, not from a
  constant you picked.
- Don't skip the "one atomic unit" behavior in the background task — a
  partial overwrite (new `foo` data saved, but a stale `land_cover` left
  in place because it happened to succeed on a run where `foo` failed) is a
  silent correctness bug, not a minor inconsistency.
- Don't reshape/rename upstream fields you haven't actually confirmed —
  Byggnad Direkt's `buildings_in_geometry` passes features through
  unchanged specifically because no field list is documented; Ortnamn's
  `place_names_search` reshapes fields, but only because Geotorget's
  documentation gives exact field names to reshape against. Match the level
  of confidence to what's actually confirmed.
- If the upstream data has no live query API at all — only bulk/static
  downloads (like Lantmäteriet's road data, see
  [land-cover-fetch-handoff.md](land-cover-fetch-handoff.md)'s "Out of
  scope") — that's a different, much bigger kind of integration (storage,
  licensing, update cadence) than anything in this checklist. Don't force it
  into the live-proxy pattern; flag it and decide the approach deliberately
  before building.
