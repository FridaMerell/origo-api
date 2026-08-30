# BirdNET

BirdNET receives short-lived acoustic detections from field devices. A device
belongs to one or more users and can optionally be associated with a house.
Detections are retained for 24 hours. Authorized frontends read new detections
live over a Server-Sent Events stream.

## Domain model

```text
User * ───────── * BirdnetDevice
                       │
                       ├── 0..1 verso.House
                       └── 1 ───── * BirdnetDetection
                                          └── 0..1 Species
```

`BirdnetDevice` contains a UUID, unique `identifier`, display `name`, `users`,
optional `house`, `is_active`, and timestamps. If a house is selected, the
requesting user and all device users must be members of it.

`BirdnetDetection` contains the required `device`, received
`scientific_name`, optional matched `species`, confidence from 0 to 1,
`detected_at`, and `created_at`. Deleting a device cascades to its detections;
deleting a species leaves the received scientific name intact.

## Flow

```mermaid
flowchart TD
    A[Microphone] --> B[BirdNET device]
    B --> C[Analyse audio]
    C --> D{Bird detected?}
    D -- No --> C
    D -- Yes --> E[Build JSON payload]
    E --> F[POST /api/birdnet/detections]
    F --> G{Valid token?}
    G -- No --> H[401 Unauthorized]
    G -- Yes --> I{Active device and authorized user?}
    I -- No --> J[Validation error]
    I -- Yes --> K[Best-effort Species match]
    K --> L[(BirdnetDetection)]
    M[(BirdnetDevice)] --> L
    N[(House, optional)] -. groups .-> M
    O[(Users)] --> M
    L --> P[201 Created]
    Q[django-tasks worker] --> R[Delete detections older than 24 hours]
    R --> S[Schedule next cleanup in one hour]
    S --> R
    L -. pg_notify on commit .-> T[SSE stream: GET /api/birdnet/detections/stream]
    T --> U[Authorized frontend]
```

## Status

- Models, device CRUD, ingest, SSE stream (PostgreSQL `LISTEN`/`NOTIFY` with a
  polling fallback), cleanup task, admin, fake-data command, and ingest/stream
  tests (`tempus/tests/test_birdnet.py`): implemented.
- Migration from the old free-text `device_id` to the device relation: existing
  values must be mapped during migration.

See [API contract](api.md) and [fake data](fake-data.md).

