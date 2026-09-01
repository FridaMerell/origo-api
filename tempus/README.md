# Tempus

Tempus is a Django app for following species, describing geographically
specific seasonal activity, recording personal observations, and planning
nature routes.

Species are referenced through SLU Artdatabanken's Dyntaxa taxon IDs. Tempus
keeps only a local cache of species needed by the application; Dyntaxa remains
the taxonomic source of truth.

## Current scope

The first version provides models for:

- locally cached species references;
- taxon-backed species categories;
- species followed by users;
- phenophases such as flowering, migration, or general activity;
- sources for seasonal information;
- geographic areas represented by polygons;
- stored per-area activity curves (phenograms) and the seasonal status
  (in season, coming into season, going out of season) derived from them;
- planned routes and ordered route stops; and
- personal checklists whose items are completed by sightings; and
- observations registered by users.

The app exposes these through Django REST Framework serializers and viewsets
under `/api/tempus/`, a Django admin registration, background tasks
(`django-tasks`), and a typed service boundary that calls SLU Artdatabanken's
Dyntaxa, Artfakta, and Species Observation System APIs. See
[`docs/tempus/`](../docs/tempus/README.md) for the API contract and feature
documentation.

## Domain model

### Species

`Species` is a local reference and cache for a Dyntaxa taxon. It uses an
internal UUID as its primary key and stores the unique external identifier in
`dyntaxa_taxon_id`.

Cached data includes scientific and Swedish names, rank, parent taxon ID,
active status, selected raw API data, and the latest synchronization time.

`landscape_types` holds the Artfakta *landskapstyper* classification as a JSON
list — `[{"id", "parent_id", "code", "name", "significance"}]`. `biotopes`
holds *biotoper* in the same shape (with `parent_id` giving the biotope
hierarchy). `significance` is folded to two levels, `"stor"` or `"har"`:
landskapstyper's *stor/har betydelse* and biotoper's *Viktig/Utnyttjas* both
map onto it. Rows with no significance are dropped. Both fields are refreshed
on every `upsert_species()` (registration and any resync) and stored as fields
rather than related tables.

Both come from `GET {information}/speciesdataservice/v1/speciesdata/<dataset>?taxa=<id>`
(`landscapetypes` / `biotopes`); the dataset path is overridable via
`ARTDATABANKEN_SPECIESDATA_{LANDSCAPES,BIOTOPES}_PATH`.

### SpeciesCategory

`SpeciesCategory` represents a general species category backed by a Dyntaxa
taxon. The category taxon may be at any useful rank, such as class, order,
family, or genus. Tempus therefore does not require all categories to use the
same taxonomic level.

For example, categories could represent birds, butterflies, bumblebees, or
orchids using the most appropriate Dyntaxa taxon for each group. An optional
`label` can override the taxon's normal display name.

`image_url` stores an optional externally hosted category image. Tempus does
not handle the upload itself; a frontend uploads the image and saves the
resulting URL.

`species` is a many-to-many to `Species` through `SpeciesCategoryMembership`
(unique per category/species) — the explicit member list, managed via
`register_species` or the admin.

Categories also form a tree through the nullable self-reference
`parent_category` (`SET_NULL`, reverse `children`). `effective_species_ids()`
returns the members of the category plus every descendant category, so a parent
category resolves the union of its subtree. `is_primary` marks the categories a
client should surface first.

### SpeciesFollow

`SpeciesFollow` connects a user with a species they want to follow. It stores a
priority, notification preference, notes, and creation time. A user can follow
each species only once. Follows are removed with
`DELETE /api/tempus/species-follows/{id}/` or, by Dyntaxa taxon id, with
`DELETE /api/tempus/species-follows/unfollow/?species=<dyntaxa-id>`.

### Phenophase

`Phenophase` describes what a seasonal window means. Possible future codes
include:

- `general_activity`
- `flowering`
- `fruiting`
- `migration`
- `breeding`
- `visible`

No phenophase seed data is included.

### GeoArea

`GeoArea` represents a general geographic area as a GeoJSON `MultiPolygon`
stored in a Django `JSONField`. Supported area kinds include countries,
counties, provinces, nature reserves, and biological areas.

An area is deliberately not assumed to belong to a Swedish province. This
allows Tempus to represent administrative areas and ecologically meaningful
regions with the same model.

### Phenogram

`Phenogram` stores the week-by-week activity curve for a species: 52 rows of
count / smoothed / fraction in `weeks`, the peak week, the ISO-week activity
window, a day-of-year envelope (`start_day_of_year`, optional
`peak_start_day` / `peak_end_day`, `end_day_of_year`, `confidence`), and
provenance (`computed_at`, `record_count`, `record_limit_hit`, `sample_count`,
`years_present`, `date_from` / `date_to`).

One row per `(species, geo_area, years)`; a NULL `geo_area` is the whole range
(no polygon clip). It is computed from Species Observation System records by
`tempus.services.phenogram.get_phenogram()`.

**Generation is asynchronous.** The SOS crawl never runs in a request.
`get_phenogram(..., create=False)` reads the stored row (or `None`); actual
building happens in the `tempus.tasks.generate_phenogram` background task
(django-tasks — run `python manage.py db_worker`). Phenograms are generated for
**every `GeoArea`**, fanned out one build task per area:

- when a `Species` is registered (`post_save` → `fan_out_species_phenograms`);
- when a `GeoArea` is created (`post_save` → `fan_out_area_phenograms`, across
  all species);
- on demand via `POST species/generate-phenograms/` (staff; `taxa` to limit,
  `refresh` default true);
- from cron / shell via `python manage.py resync_phenograms` (stale or missing
  curves by default; `--older-than DAYS`, `--all`, `--taxon`, `--no-refresh`,
  `--dry-run`);
- `GET species/<id>/phenogram/` for a missing row returns `202` and enqueues
  one build; `POST` with `refresh` always enqueues and returns `202`.

Nothing rebuilds a phenogram on a plain read, so `GET species/<id>/phenogram/`
is safe to call on every render (it just may 202 until the worker catches up).

The envelope may cross New Year; a `start_day_of_year` of 320 with an
`end_day_of_year` of 40 is valid.

### Seasonal status

Seasonal status is **calculated, never stored** — Tempus has no
`is_in_season` / `is_last_chance` database fields.
`tempus.services.season.status_for(phenogram)` reads a stored phenogram's
day-of-year envelope and returns where today sits in it:

- `status` — one of `out_of_season`, `coming_into_season`, `in_season`,
  `at_peak`, `going_out_of_season`;
- `is_in_season`, `is_coming_into_season`, `is_going_out_of_season`, `at_peak`
  — overlapping booleans (`is_in_season` stays true at peak and through the
  last-chance tail);
- `days_until_start`, `days_until_end` — whole days forward to each edge.

The thresholds (`coming_into_season` within 21 days of the start,
`going_out_of_season` within 14 days of the end) live in
`tempus.services.season`. The underlying maths is
`tempus.services.phenology.phenogram_status()`.

It is exposed two ways:

- every phenogram payload carries a `seasonal_status` object
  (`GET species/<id>/phenogram/`, `GET phenograms/`);
- `GET phenograms/?status=<name>` lists the phenograms currently in a given
  state — `?status=going_out_of_season&geo_area=<id>` answers "what is my last
  chance to see on Öland". `status` also accepts `species=` and `years=`.
- `notify_followed_species_season_start` creates an in-app Tempus notification
  every Sunday for followed species whose phenogram season starts 7-14 days
  later. All matching species for one user are grouped into one digest, and a
  species is not repeated in another digest within the following 14 days.
  Enqueue it once from the Django task/operations setup; it schedules its next
  weekly run itself. Notifications are read through
  `/api/accounts/notifications/`.

`Species` mirrors this with `seasonal_status(geo_area=None)`, `is_in_season()`,
`is_coming_into_season()` and `is_going_out_of_season()`, each reading the
species' phenogram for that area (the whole-range row when omitted).

### Source

`Source` records the title, URL, publisher, and access time for seasonal
information. A seasonal window may refer to a source, while retaining the
window if that source is later removed.

### Route and RouteStop

`Route` stores a user's planned route as a GeoJSON `LineString` in a Django
`JSONField`. `corridor_metres` defines the distance around the line that should
be treated as the route's search area.

Route availability should eventually be evaluated by buffering the route by
this distance and checking which geographic areas overlap the resulting
corridor.

`RouteStop` stores ordered points along a route. Each sequence number is unique
within its route, and stops are ordered by sequence by default.

### Checklist and ChecklistItem

`Checklist` is a user-owned species list. It has a name and optional
description and may be associated with a planned date, geographic area, and
route. This supports lists such as "Kristianstad in June" or "Öland in July"
without requiring every checklist to have geographic or route context.

`ChecklistItem` connects one species to a checklist and provides an explicit
display sequence and optional notes. A species and a sequence number may each
occur only once within the same checklist.

Checklist completion is derived from sightings. It is not stored as an
`is_completed` boolean. An item with one or more linked observations is
complete, and the earliest or latest sighting time can be obtained from those
observations as needed.

### Observation

`Observation` represents an observation registered by a Tempus user. It stores
the species, time, GeoJSON point, optional count, and notes. It has an optional
plain many-to-many to `ChecklistItem` (`checklist_items`, reverse
`item.observations`). An observation can therefore exist independently or check
off matching items in several checklists at once, and an item can have multiple
observations.

The `record_checklist_sighting()` service verifies that the observation user
owns every selected checklist, verifies that all selected items refer to the
same species, and creates one observation linked to all of them atomically. The
`ObservationSerializer` calls it when `checklist_items` are supplied. The
behavior stays in the service layer rather than a model's `save()` method.

This table is not intended to mirror or import the complete Artportalen
observation database. External observations should be queried through the
appropriate API using taxon ID, time interval, and geometry.

## Example: Kristianstad in June and Öland in July

One species can have a different phenogram (and therefore a different envelope)
per area. The dates below are illustrative and are not real biological data.

```text
Example species
├── Kristianstad phenogram
│   ├── starts: 1 June (day 152)
│   ├── peak: 10–25 June
│   └── ends: 5 July (day 186)
└── Öland phenogram
    ├── starts: 25 June (day 176)
    ├── peak: 5–20 July
    └── ends: 31 July (day 212)
```

This means the species could be shown `at_peak` in Kristianstad on 15 June but
`out_of_season` on Öland. On 10 July the Öland phenogram is at peak while the
Kristianstad one has ended (`out_of_season`, or `going_out_of_season` in the
last 14 days before its end).

The core lookup is based on:

```text
followed species
+ today inside the day-of-year envelope of a matching Phenogram
+ selected place or route overlapping that Phenogram's GeoArea
= currently relevant species
```

## Artdatabanken service

The integration boundary is located in
`tempus/services/artdatabanken.py` and defines:

- `search_taxa(query)`
- `get_taxon(taxon_id)`
- `get_species_information(taxon_id)`
- `get_species_landscapes(taxon_id)` / `get_species_biotopes(taxon_id)`
- `upsert_species(taxon_id)`
- `register_species(category, dyntaxa_taxon_id)`
- `stale_species(...)` / `resync_species_batch(...)`

`upsert_species()` is responsible for fetching normalized taxon and species
information (Dyntaxa taxonomy plus best-effort Artfakta species info,
*landskapstyper* and *biotoper*), creating or updating the local `Species`
cache, storing relevant raw data, and updating `synced_at`. It is also the
resync path: it is `update_or_create`, so calling it for an already-cached
taxon refreshes that row in place.

Resync is exposed three ways:

- `POST species/<id>/resync/` — staff only; re-runs `upsert_species` for one
  species and returns the refreshed row;
- `POST species/resync/` — staff only; bulk. Body (all optional): `taxa` (list
  of dyntaxa ids), `missing` (list of `biotopes` / `landscape_types` — species
  whose that field is empty, for backfilling a newly added Artfakta field),
  `all` (`true` = every species), or neither to take species not synced within
  `older_than_days` (default 30) plus any never synced. Runs synchronously, one
  atomic upsert per species; returns
  `{"synced": [...], "failed": [{"dyntaxa_taxon_id", "detail"}]}`;
- `python manage.py resync_species` — same selection, for cron / shell:
  `--older-than DAYS`, `--all`, `--taxon <id>` (repeatable),
  `--missing biotopes` (repeatable), `--dry-run`.

The HTTP adapter is implemented: `tempus/services/artdatabanken.py` calls
Dyntaxa, Artfakta, and the Species Observation System over `requests`, with a
shared cross-process request cooldown. Each product needs its own
`Ocp-Apim-Subscription-Key`; a call made without the required configuration
raises `ArtdatabankenConfigurationError`, and a non-success HTTP response
raises `ArtdatabankenAPIError`. Base URLs, keys, timeouts, and the cooldown are
set through environment variables — see
[`docs/tempus/artdatabanken/authentication.md`](../docs/tempus/artdatabanken/authentication.md).
OAuth (for protected SOS coordinates and Artportalen writes) is not
implemented.

API requests must remain in the service layer and must never be added to model
`save()` methods.

## Geographic data storage

Tempus stores geographic values as standard GeoJSON geometry objects in Django
`JSONField`s. This works with ordinary PostgreSQL or the project's SQLite
fallback and requires no separate GIS runtime.

The expected GeoJSON geometry types are:

- `GeoArea.geometry`: `MultiPolygon`
- `Route.geometry`: `LineString`
- `RouteStop.location`: `Point`
- `Observation.location`: `Point`

Coordinates use WGS 84 longitude/latitude order. For example:

```json
{"type": "Point", "coordinates": [14.1567, 56.0294]}
```

The API serializers validate the geometry type and presence of coordinates.
More detailed coordinate validation, route buffering, and polygon overlap must
be implemented in the application layer or delegated to a suitable mapping
service. Because these are JSON fields, the database does not provide native
spatial indexes or intersection queries.

## Migrations

Run the project's normal migration flow yourself from the Django project root
after changing models:

```powershell
python manage.py makemigrations tempus
python manage.py migrate
```

## Suggested next steps

1. Configure the normal PostgreSQL connection used by the project.
2. Create initial phenophases through the project's chosen data-management
   process.
3. Add route-corridor spatial queries.
4. Add protected-SOS/Artportalen OAuth when access is granted (see
   [`docs/tempus/artdatabanken/`](../docs/tempus/artdatabanken/README.md)).
5. Extend the existing serializers and endpoints as their API contract evolves.
