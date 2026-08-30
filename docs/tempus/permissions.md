# Permissions

Tempus uses DRF session authentication by default. The BirdNET ingest endpoint
is the exception and explicitly uses DRF token authentication. The BirdNET SSE
stream uses the default session authentication (an `EventSource` cannot send an
`Authorization` header).

## Permission groups

| Resource | Read | Write |
|---|---|---|
| Species, categories, phenophases, sources, GeoAreas | Authenticated users | Staff only |
| Phenograms | Authenticated users | Read-only; builds through species actions |
| Species follows | Current user's rows | Current user |
| Routes and route stops | Current user's rows | Current user |
| Checklists, items, observations | Current user's rows | Current user |
| BirdNET devices | Device users | Device users, with house validation |
| BirdNET ingest | Token-authenticated device user | One detection per request |
| BirdNET stream | Session user; only their devices' detections | Read-only SSE |

Shared data uses `SharedDataPermission`: safe HTTP methods require an
authenticated user; mutation methods also require staff.

## Object scoping

User-owned viewsets filter their queryset before retrieve/update/delete. A user
therefore normally receives 404 for another user's object, avoiding disclosure
that the object exists.

Related-field validation additionally prevents cross-owner references:

- route stops and checklists cannot reference another user's route;
- checklist items cannot reference another user's checklist;
- observation checklist items must all belong to the user and match species;
- a BirdNET device house must include the requesting user;
- when a device has a house, submitted device users must be house members;
- ingest requires the token user to be attached to the active device.

## Frontend sessions

Cross-subdomain frontend requests use session cookies with credentialed CORS
and CSRF trusted origins. Mutation requests must include the normal CSRF token.
Device-side ingestion instead sends `Authorization: Token <key>` and does not
use a browser session.

