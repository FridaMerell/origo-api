# Tempus API index

Base prefix: `/api/tempus/`, except the BirdNET endpoints. Standard router resources
support trailing slashes. Unless stated otherwise, authentication is the normal
DRF browser/session authentication; `Authorization: Token <key>` is also
accepted for non-browser clients (see [Accounts tokens](../accounts/README.md#tokens)
for issuing one).

## Shared reference data

Authenticated reads; staff-only writes.

| Path | Operations and filters |
|---|---|
| `species/` | CRUD; search names; responses include aggregated `stages` from the species' categories; filters include Dyntaxa ID, rank, active state, and category |
| `species-categories/` | CRUD; URL lookup and detail addressed by `taxon_id`; list and detail responses include `stages`; new children copy their parent's stages when created. Filters `taxon_id`, `parent_category`, `is_primary`; ordering by `taxon_id`, `label`, `parent_category`, `parent_category__label`, `is_primary`; list is paginated and lighter than the detail payload |
| `phenophases/` | CRUD; filter `code` |
| `sources/` | CRUD |
| `geo-areas/` | CRUD; filters `kind`, `country_code`; list responses carry `Cache-Control: private, max-age=3600` |

Species actions:

| Method and path | Purpose |
|---|---|
| `GET species/search/?q=...` | Search Dyntaxa; optional `under_taxon_id`, `limit`. When `under_taxon_id` identifies a Tempus category, every result includes that category's `stages`. |
| `POST species/resolve/` | Read-only bulk fetch: body `{ "ids": [<species-uuid>, ...] }` (max 100, unique); returns the matching cached species without touching state |
| `POST species/register/` | Register one Dyntaxa taxon in a category |
| `POST species/import-checklist/` | Queue multipart CSV import |
| `POST species/{dyntaxa-id}/resync/` | Refresh one cached species |
| `POST species/resync/` | Bulk/stale/missing-field resync |
| `GET species/{dyntaxa-id}/phenogram/` | Read or queue one curve |
| `POST species/{dyntaxa-id}/phenogram/` | Request refresh/build |
| `POST species/generate-phenograms/` | Staff bulk fan-out |
| `GET species/seasonal-overview/` | Paginated seasonal cards; requires `geo_area`, with `min_records`, `status`, and `is_followed` optional |

Regular `GET species/` and `GET species/{dyntaxa-id}/` responses include a
`checklists` array scoped to the authenticated user. Every entry has the
 checklist `id`, its `name`, `auto_add` setting, and `item_id`, which is the
 value to send in an observation's `checklist_items` array for explicit
 registration.

## Seasonal data

### Seasonal overview cards

`GET /api/tempus/species/seasonal-overview/?geo_area=<uuid>` returns one
current-season card per species from already stored eight-year phenograms. It
never starts an SOS fetch or rebuild in the request cycle.

The default statuses are `coming_into_season`, `at_peak`, `in_season`, and
`going_out_of_season`, so the start page has useful results throughout the
active season. Pass a comma-separated `status` value to choose a narrower
selection, `min_records` to set the confidence threshold (default `20`), and
`is_followed=true` to limit results to followed species.

For each species, Tempus prefers the selected area's phenogram. If there is no
such row, it falls back to the stored whole-range row (`geo_area: null`). Rows
below `min_records` remain eligible as a last-resort card instead of being
silently excluded. The response identifies these cases with:

- `phenogram_scope`: `selected_area` or `whole_range`;
- `is_low_confidence`: true when `record_count < min_records`;
- `confidence` and `years_present`: the stored evidence behind the curve.

Clients should explain a `whole_range` card as non-local data and label a
low-confidence card accordingly.

Results are ordered followed-first, then by status priority, local curve before
whole-range, higher confidence, and finally by name. When `is_followed=true` is
given without an explicit `status`, the status set is widened to every state and
the result is capped at 15 cards so out-of-season follows do not crowd the view.

| Path | Operations and filters |
|---|---|
| `phenograms/` | Read-only; `species`, `geo_area`, `years`, `status` |

Notifications are available at `/api/accounts/notifications/` — read-only for
the current user, with `domain`, `is_read`, and `unread` filtering plus
`summary/`, `{id}/read/`, and `read-all/` actions (see
[Accounts](../accounts/README.md#notifications)). The Tempus season
notification is delivered as one combined weekly digest when followed species
start their season 7-14 days later.

## User-owned resources

| Path | Operations and filters |
|---|---|
| `species-follows/` | CRUD for current user; `species`, `priority`, `notifications_enabled`. `GET species-follows/my_follows/` returns the caller's follows unpaginated (same queryset as the list endpoint). `DELETE species-follows/unfollow/?species=<dyntaxa-id>` removes the caller's follow addressed by Dyntaxa taxon id (`204`, or `404` if not followed) |
| `routes/` | CRUD for current user; `planned_date` |
| `route-stops/` | CRUD for current user's routes; `route` |
| `locales/` | CRUD for current user; `name` and GeoJSON `MultiPolygon`. The server sets the read-only `user` field. Includes `GET {id}/land-cover/`, `GET {id}/land-cover/map/`, `GET {id}/land-cover/fetch/` (status of the background land-cover + hydrography + place-name + building prefetch for the Locale + 5 km padding; see [land-cover-fetch-handoff.md](land-cover-fetch-handoff.md)), `GET {id}/administrative-boundaries/`, `GET {id}/place-names/` (nearest Ortnamn Direkt place name to a point), `GET {id}/place-names/search/` (name/county/municipality search kept to points inside the Locale), `GET {id}/buildings/` (OpenStreetMap building footprints, exactly clipped to the Locale), and `GET {id}/roads/` (Trafikverket road segments, exactly clipped to the Locale); see [Lantmäteriet marktäcke](lantmateriet-marktacke.md), [Lantmäteriet Ortnamn Direkt](lantmateriet-ortnamn.md), [OpenStreetMap buildings](openstreetmap-buildings.md), and [Trafikverket roads](trafikverket-roads.md). |
| `administrative-boundaries/` | Viewport-based Lantmäteriet municipality, county, and country GeoJSON layer; it requires `bbox=minLon,minLat,maxLon,maxLat` and accepts optional `kinds=municipality,county,country`. See [Lantmäteriet documentation](lantmateriet-marktacke.md). |
| `land-cover/` | Viewport-based Lantmäteriet land-cover and wetland GeoJSON layer. Requires `bbox=minLon,minLat,maxLon,maxLat`; optional `kinds=land_cover,wetland`. Lantmäteriet only — no CORINE or other fallback. See [Lantmäteriet documentation](lantmateriet-marktacke.md). |
| `land-cover-by-type/` | Viewport-based Lantmäteriet land-cover layer filtered to specific `objekttyp` values, filtered server-side by Lantmäteriet (CQL2), not fetched in full and filtered locally. Requires `bbox=minLon,minLat,maxLon,maxLat` and `types=<objekttyp>,<objekttyp>,...` (exact, case-sensitive values, e.g. `types=Barr- och blandskog,Åker`); optional `kinds=land_cover,wetland`. Same viewport-size limit as `land-cover/`'s full-detail tier; no degraded fallback. See [Lantmäteriet documentation](lantmateriet-marktacke.md). |
| `country-overview/` | Static, pre-generated whole-country overview: `basemap` (OpenFreeMap style/initial view), generalised `outline`, major `waterways`, and `cities`. Regenerated offline via `manage.py generate_country_overview`, not fetched live. `503` if not yet generated. See [Lantmäteriet documentation](lantmateriet-marktacke.md). |
| `checklists/` | CRUD for current user; `start_date`, `geo_area`, `route`, `locale`; `auto_add` controls automatic observation linking. `POST {id}/sync-category/` adds all missing species from a category subtree. `GET {id}/register/` returns paginated checklist-item rows (see [Observations and checklists](observations-and-checklists.md#checklist-register-rows)). |
| `checklist-items/` | CRUD for current user's checklists; `checklist`, `species` |
| `observations/` | CRUD for current user; `checklist_items`, `locale`, optional `life_stage`, and `species` (accepts either a Species UUID or a Dyntaxa taxon id). GET responses include read-only `species_detail` with `dyntaxa_taxon_id` and `swedish_name`, and `checklist_names` (the names of every linked checklist). `GET observations/by-category/` lists the caller's actual observation category groups (paginated, count-only); `GET observations/by-category/{categoryId}/` returns one category's observations, paginated; `POST observations/sync-checklists/` re-links the caller's existing observations to any checklist items they newly satisfy and returns `{"observations_linked", "checklist_item_links_created"}`. |
| `birdnet-devices/` | CRUD for devices shared with current user |

### Synchronize a checklist category

`POST checklists/{id}/sync-category/` accepts
`{ "species_category_id": "<category-uuid>" }`. It adds every missing species
from that category and all of its descendants to the current user's checklist.
Existing items are retained, and the response is
`{ "species_category_id", "species_added", "species_count" }`. The action is
idempotent for an unchanged category and never removes existing checklist
species. See [Observations and checklists](observations-and-checklists.md#update-a-checklist-from-a-species-category)
for the full request and response examples.

Route calculation:

- `POST routes/{id}/suggested-stops/`: start/reuse background run.
- `GET routes/{id}/suggested-stops/`: poll current run.
- `GET routes/{id}/suggested-stops/?sync=true`: inline debugging only.

## BirdNET

Outside the `/api/tempus/` prefix, no trailing slashes:

- `POST /api/birdnet/detections` - ingest one detection; `Authorization: Token <key>`.
- `GET /api/birdnet/detections/stream` - live SSE stream of the session user's
  detections; supports `Last-Event-ID` resumption and `?replay_seconds=`.

See [BirdNET API](birdnet/api.md).

## Common responses

- `200`: successful read/update/action.
- `201`: created resource or accepted BirdNET detection.
- `202`: background computation/import queued.
- `400`: serializer or domain validation failure.
- `401`: missing/invalid authentication.
- `403`: authenticated but staff/action permission denied.
- `404`: missing object or object outside the user's scoped queryset.
- `413`: a Lantmäteriet map/viewport layer exceeded the configured feature
  safety limit; see [Lantmäteriet documentation](lantmateriet-marktacke.md).
- `429`: a Lantmäteriet endpoint was rate-limited upstream; the response
  forwards `Retry-After` when Lantmäteriet supplied one.
- `502`: upstream Artdatabanken or Lantmäteriet API failure exposed by a
  synchronous action.
- `503`: missing external API configuration.

This page is an index, not a replacement for serializer-specific contracts.
Feature pages document the important payloads and state transitions.
