# Verso API documentation

Verso is Origo's shared-house API. It covers homes, bookings, checkout notes,
maintenance ventures, venture tasks, expenses, activity updates, measured
drawings, and photos.

Base prefix: `/api/verso/`. All endpoints require authentication and use
trailing slashes. A user can only see data belonging to a house they are a
member of; inaccessible rows appear as `404` on detail requests.

## Resources

| Resource | Purpose | Filters |
|---|---|---|
| `houses/` | House name, address, position, and members | `members` |
| `bookings/` | Visits to a house | `house`, `future` |
| `booking-requests/` | Proposed visits | `house`, `status` |
| `check-outs/` | Checkout timestamp, notes, and file metadata | `booking`, `booking__house` |
| `ventures/` | House maintenance/projects | `house` |
| `venture-tasks/` | Tasks within a venture | `venture`, `completed`, `venture__house` |
| `expenses/` | Expenses tied to a house and/or venture | `house`, `venture` |
| `updates/` | Updates for a house, venture, or venture task | `venture`, `task`, `author`, `house` |
| `drawings/` | Measured drawings (e.g. windows, panels, gardens) for a house | `house`, `venture` |
| `drawing-pages/` | Pages of a drawing (e.g. one facade), holding the drawing elements | `drawing`, `drawing__house` |
| `photos/` | Photos of a house or venture (everyday, before/after, later image bank) | `house`, `venture`, `task`, `albums`, `tags`, `people`, `stage` |
| `albums/` | Named photo collections | `house`, `venture`, `kind` |
| `photo-tags/` | Tags for photos and documents, unique per house | `house` |
| `documents/` | Arbitrary documents (maps, deeds, PDFs...) for a house | `house`, `venture`, `tags`, `people`, `content_type` |
| `people/` | People in a house's history (family, previous owners, interviewees) | `house` |
| `person-relations/` | Family ties between two people | `house`, `person`, `related`, `kind` |
| `history-events/` | Dated events in a house's history | `house`, `people`, `photos`, `date_precision` |

Each resource supports the standard list, retrieve, create, update, and delete
operations. Creating a house automatically adds the caller as a member.

## Rules and relationships

- Bookings, booking requests, ventures, and house-level expenses must belong
  to a house the caller belongs to.
- A venture must belong to a house. Venture tasks belong to a venture.
- An expense must have a house, a venture, or both. When both are supplied,
  the venture must belong to that house.
- An update must relate to at least one of a house, venture, or task. If more
  than one is supplied, they must resolve to the same house. The API sets its
  `author` to the caller on creation.
- A drawing must belong to a house the caller belongs to and may optionally
  link to a venture, which must belong to the same house. `unit` is `mm`
  (default), `cm`, or `m`. The API sets `author` to the caller on creation.
  `pages` on a drawing is a read-only list of page ids.
- A drawing page has `name`, `order`, `width`, `height` and `elements`. It is
  a canvas in real-world units (the drawing's `unit`), not a paper sheet, so
  there is no scale or title block.
- `elements` is a list of objects, each with a `type` of `line`, `polyline`,
  `polygon`, `rect`, `ellipse`, `dimension`, `text`, or `note`. Other fields
  are free-form and defined by the client, except those used for area:
  - `rect` uses `width` and `height`; `polygon` uses `points` as `[[x, y], ...]`.
  - An optional `role` of `surface` or `opening` marks a rect/polygon as
    something to cover (e.g. a facade) or to subtract (a window or door).
- A drawing page returns a read-only `area` with `surface_m2`, `openings_m2`
  and `net_m2`, computed from the elements with a `role`. Use `net_m2` as the
  basis for material calculations such as boards for a facade.
- A photo must belong to a house the caller belongs to. Files are hosted by
  the frontend; the API stores only `url` and optional `thumbnail_url`,
  `width` and `height`. Other fields: `title`, `description`, `taken_at`,
  `lat`, `lng`. The API sets `author` to the caller on creation.
  - `venture` must belong to the same house; `task` must belong to the
    photo's venture.
  - `stage` is `before`, `during`, `after`, or empty. `pair` links a photo to
    its counterpart (e.g. before → after); it must be in the same house, not
    the photo itself, and is one-to-one. `paired_with` is not exposed.
  - `albums` and `tags` are lists of ids and must belong to the same house.
- An album has `name`, `description`, `kind` (`general`, `progress`,
  `history`), an optional `venture` and `cover` photo (same house), and a
  read-only `photo_count`. `history` is reserved for the future image bank.
- `photos/` also filters on `album_kind` (`general`, `progress`, `history`),
  e.g. `photos/?album_kind=history&house=<id>`. `photos/` and `documents/`
  support `?ordering=` (prefix `-` for descending): photos by `taken_at`,
  `created_at`, `title`; documents by `document_date`, `created_at`, `title`.
  Photos default to newest `taken_at` first. Items without a date sort last
  or first depending on the database, so prefer sending dates.
- A photo tag has a `name`, unique within its house. The same tags are used
  for documents.
- A document must belong to a house the caller belongs to. Like photos, the
  file is hosted by the frontend and only `url` is stored, with optional
  `file_name`, `content_type` and `size`. Other fields: `title`,
  `description`, `document_date` with `date_precision` (as for photos),
  `source` and `transcription` (plain text). `venture` must be in the same
  house; `tags` and `people` are lists of ids in the same house. The API sets
  `author` to the caller.
- History photos also use `date_precision` (`day` default, `month`, `year`,
  `decade`, `circa`) alongside `taken_at`, plus `place`, `source` (free text
  provenance), `transcription` (plain-text transcription of writing in the
  image, e.g. a letter or map labels), `credit` (photographer/rights) and `people` (ids of depicted
  people). Old photos and maps are ordinary photos, typically in an album of
  kind `history`.
- A person has `name`, optional `birth_date` and `death_date` (death not
  before birth), `relation` and `notes`. Each date has a
  `birth_date_precision`/`death_date_precision` (`day` default, `month`,
  `year`, `decade`, `circa`). For year-only knowledge send any date in that
  year with precision `year`; clients show just the year. `portrait` is an
  optional photo id (same house) used as the person's main picture. To list
  all photos of a person use `photos/?people=<id>`. The response includes
  read-only `portrait_url` and `portrait_thumbnail_url` (`null` without a
  portrait), so lists need no extra photo requests.
- Deleting a person is never blocked. It removes the person's relations (both
  directions) and their links to photos, history events and documents; the
  photos, events and documents themselves remain. Photos are not deleted with
  the person, and a person's `portrait` is just a link, so nothing else
  changes. `DELETE` returns `204`; there is no dependency error to handle.
- A person relation links `person` to `related` with a `kind` of `parent`,
  `spouse`, `partner`, `sibling` or `other`, plus optional `start_year`,
  `end_year` (not before start) and `notes`. `label` is a free-text
  description such as "adoptivson"; it is optional, but required when `kind`
  is `other`. Use `kind` for the structural tie (so the tree can be derived)
  and `label` for the exact wording. For `parent`, `person` is the
  parent of `related`. The other kinds are symmetric: store each pair once
  (the mirrored duplicate is rejected). Both people must be in the relation's
  house, cannot be the same person, and a `(person, related, kind)` triple is
  unique. Children, grandparents etc. are derived by the client from these.
- A history event has `title`, `description`, `date_start`, optional
  `date_end` (not before start), `date_precision` (default `year`), `place`,
  `lat`, `lng`, `source`, `transcript` (plain text, e.g. a transcribed
  interview; there is no separate interview resource), and `people` and
  `photos` (ids). `photos_detail` is a read-only list of
  `{id, title, thumbnail_url}` for the linked photos (`thumbnail_url` falls
  back to the full `url`). The API sets `author` to the caller.
- All ids linked from photos and events must belong to the same house as the
  record.
- `files` fields contain client-managed JSON file metadata; they are not file
  upload endpoints.

## Summary endpoints

| Path | Method | Purpose |
|---|---|---|
| `houses/dashboard/?house=<id>&year=<year>` | GET | Return the selected (or first accessible) house plus its bookings, requests, checkouts, ventures, tasks, expenses, updates, and yearly expense total. |
| `houses/on_this_day/?house=<id>&date=<YYYY-MM-DD>` | GET | "On this day": history events, photos and people's births/deaths from earlier years on the same month and day. Returns `date`, `events`, `photos`, `births` and `deaths`, each item with `years_ago`. |
| `expenses/year_expenses/?house_id=<id>&year=<year>` | GET | Return the total expenses for the house in the requested year. |

`house` is required for `on_this_day`; `date` defaults to today. Only events
(by `date_start`), photos (by `taken_at`) and people (by `birth_date` /
`death_date`) with a precision of `day` match, since month/day is meaningless for year- or decade-dated material.
Items from the same year as `date` or later are excluded.

`year` defaults to the current year. `bookings/?future=true` returns bookings
whose start date is today or later; `future=false` returns earlier bookings.
