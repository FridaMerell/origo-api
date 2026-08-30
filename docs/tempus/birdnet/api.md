# BirdNET API contract

## Device management

Base path: `/api/tempus/birdnet-devices/`

The DRF router provides list, create, retrieve, update, partial update, and
delete. Calls use normal frontend session authentication. Users only see
devices connected to them; objects outside that queryset return 404. The
creator is automatically added to `users`.

```json
{
  "identifier": "pi-birdnet-001",
  "name": "Garden microphone",
  "users": ["<user-primary-key>"],
  "house": 12,
  "is_active": true
}
```

`users` may be omitted on create and `house` may be null. With a house, the
requesting user and all submitted users must be house members.

## Detection ingest

Endpoint: `POST /api/birdnet/detections` (no trailing slash).

```http
Authorization: Token <device-user-token>
Content-Type: application/json
```

The original `X-Api-Key` header is not accepted by the current implementation.

```json
{
  "species": "Turdus merula",
  "confidence": 0.92,
  "detectedAt": "2026-08-30T12:34:56.123456+00:00",
  "device_id": "pi-birdnet-001"
}
```

The device must exist, be active, and include the token user. Species matching
is case-insensitive and best-effort; the scientific name is always stored.
Success returns `201`; invalid input returns `400`; invalid authentication
returns `401`.

The `201` body (and every streamed event) carries the resolved taxon as
`matched_species`, or `null` when the posted name matched nothing:

```json
{
  "id": "…",
  "species": "Turdus merula",
  "matched_species": {
    "id": "…",
    "dyntaxa_taxon_id": 103026,
    "scientific_name": "Turdus merula",
    "swedish_name": "Koltrast"
  },
  "confidence": 0.92,
  "detectedAt": "2026-08-30T12:34:56.123456+00:00",
  "device_id": "pi-birdnet-001",
  "created_at": "2026-08-30T12:34:57.000000+00:00"
}
```

## Live detection stream (SSE)

Endpoint: `GET /api/birdnet/detections/stream` (no trailing slash).

Server-Sent Events over the normal frontend session (`EventSource` sends the
session cookie; no token, no extra headers). The stream is always scoped to
`request.user -> BirdnetDevice.users` - a client only ever receives detections
from devices attached to the requesting user. There is no global stream.

Content negotiation is bypassed on this view, so any `Accept` header (or none)
is served the stream rather than a `406`.

Events:

```text
id: 2026-08-30T12:34:56.123456+00:00|1f0e...c3
event: detection
data: {"id": "...", "species": "Turdus merula", "matched_species": {...},
       "confidence": 0.92, "detectedAt": "2026-08-30T12:34:56+00:00",
       "device_id": "pi-birdnet-001", "created_at": "2026-08-30T12:34:57+00:00"}
```

The `data` payload is the same shape as the ingest response, including
`matched_species` (`null` when unmatched). A `: keep-alive`
comment is sent at least every 15 s so idle connections and proxies stay open.

### How new rows are picked up

On PostgreSQL the stream blocks on `LISTEN birdnet_detection` and is woken by a
`NOTIFY` that a `post_save` signal emits (via `pg_notify`) once each new
`BirdnetDetection` row commits. The notify payload is `{"id", "device_id"}` and
is only a wake hint - every wake is confirmed by a cursor query scoped to the
user's devices, so nothing is missed or duplicated even if a notification is
coalesced or dropped. The user's device set is refreshed at most once a minute
so a newly shared device starts streaming without a reconnect.

The stream falls back to a one-second poll of the same cursor query when the
backend is not PostgreSQL (e.g. local SQLite) or when the dedicated listen
connection cannot be opened or is lost mid-stream.

`bulk_create` does not fire the signal, so history written that way (the
`fake_birdnet_detections` bulk mode) is not pushed live; single-row `create`
(real ingest, and `fake_birdnet_detections --interval`) is.

Resumption and backfill:

- The `id` of each event is `<created_at ISO>|<detection UUID>`. On reconnect
  `EventSource` replays it as the `Last-Event-ID` header and the stream resumes
  strictly after that row, so no detection is missed or duplicated.
- Without `Last-Event-ID`, the stream starts from "now". Pass
  `?replay_seconds=<n>` (0-86400) on the first connect to also emit detections
  from the last `n` seconds, e.g. to populate an initial list.

Because each connection holds a worker/thread for its lifetime, serve this
endpoint from a deployment that streams responses (async server or a dedicated
pool) and expect proxies to need response buffering disabled - the view already
sends `X-Accel-Buffering: no` and `Cache-Control: no-cache`.

