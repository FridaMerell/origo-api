# Tempus API index

Base prefix: `/api/tempus/`, except the BirdNET endpoints. Standard router resources
support trailing slashes. Unless stated otherwise, authentication is the normal
DRF browser/session authentication.

## Shared reference data

Authenticated reads; staff-only writes.

| Path | Operations and filters |
|---|---|
| `species/` | CRUD; search names; filters include Dyntaxa ID, rank, active state, and category |
| `species-categories/` | CRUD; lookup by `taxon_id`, filter `taxon_id` |
| `phenophases/` | CRUD; filter `code` |
| `sources/` | CRUD |
| `geo-areas/` | CRUD; filters `kind`, `country_code` |

Species actions:

| Method and path | Purpose |
|---|---|
| `GET species/search/?q=...` | Search Dyntaxa; optional `under_taxon_id`, `limit` |
| `POST species/register/` | Register one Dyntaxa taxon in a category |
| `POST species/import-checklist/` | Queue multipart CSV import |
| `POST species/{dyntaxa-id}/resync/` | Refresh one cached species |
| `POST species/resync/` | Bulk/stale/missing-field resync |
| `GET species/{dyntaxa-id}/phenogram/` | Read or queue one curve |
| `POST species/{dyntaxa-id}/phenogram/` | Request refresh/build |
| `POST species/generate-phenograms/` | Staff bulk fan-out |
| `GET species/seasonal-overview/` | Paginated seasonal cards; requires `geo_area`, with `min_records`, `status`, and `is_followed` optional |

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

| Path | Operations and filters |
|---|---|
| `phenograms/` | Read-only; `species`, `geo_area`, `years`, `status` |

Notifications are available at `/api/accounts/notifications/`. They are
read-only for the current user and support `domain`, `is_read`, and `unread`
filtering. The Tempus season notification is delivered as one combined weekly
digest when followed species start their season 7-14 days later.

## User-owned resources

| Path | Operations and filters |
|---|---|
| `species-follows/` | CRUD for current user; `species`, `priority`, `notifications_enabled` |
| `routes/` | CRUD for current user; `planned_date` |
| `route-stops/` | CRUD for current user's routes; `route` |
| `checklists/` | CRUD for current user; `start_date`, `geo_area`, `route` |
| `checklist-items/` | CRUD for current user's checklists; `checklist`, `species` |
| `observations/` | CRUD for current user; `species`, `checklist_items` |
| `birdnet-devices/` | CRUD for devices shared with current user |

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
- `502`: upstream Artdatabanken API failure exposed by a synchronous action.
- `503`: missing external API configuration.

This page is an index, not a replacement for serializer-specific contracts.
Feature pages document the important payloads and state transitions.
