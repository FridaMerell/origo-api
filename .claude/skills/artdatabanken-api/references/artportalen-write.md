# Artportalen — Species Observations Read and Write API

**Status for this account: NOT granted.** This is the API that actually writes
species observations into Artportalen. SLU groups it (and the Artportalen-only
Read API) under *"API:er för särskild Artportalen-funktionalitet"*, which is
outside the products this account subscribes to.

There is **no other way** to report observations into Artportalen
programmatically — the open SOS API is read-only.

## Getting access

1. Sign in to <https://api-portal.artdatabanken.se/>.
2. Check current subscriptions under your profile → *Products* to confirm you
   really lack it (see the "verify" note below).
3. The product ("Artportalen – Species Observations Read and Write") is marked
   *closed to new developers*. Request an exception via the portal's API contact
   form / SLU Artdatabanken support. Explain: the project (Tempus), the expected
   volume, and that you want **sandbox** access first.
4. On approval you get: a subscription key for the product, an OAuth
   `client_id` / `client_secret`, a registered redirect URI, the write scope,
   and the assigned base URL (production + sandbox).

### Verify what you're subscribed to

On the portal, *Profile* lists your subscriptions with their keys. Or call any
endpoint of a product with its key — 401/403 "subscription" errors mean not
subscribed; auth-scope errors mean subscribed but missing OAuth.

## Sandbox

A test environment running against a **copy** of the Artportalen database is
available for this product — build and test every write path there before
touching production. The sandbox has its own base URL and its own keys, issued
with the grant. Product name on the portal is prefixed *"Sandbox …"*.

## Auth

Subscription key **plus** OAuth 2.0 bearer (Authorization Code + PKCE) against
`https://ids.artdatabanken.se` — see [auth.md](auth.md). The write scope is
assigned with the grant. Writes are performed **as a specific Artportalen user**,
so the OAuth flow must involve that user's consent (or a service account SLU
provisions for you).

## Expected reporting payload (design target, verify on grant)

The write API is versioned separately (historically `/sighting/vN`). A reported
sighting broadly needs:

```jsonc
{
  "taxonId": 102822,                       // Dyntaxa taxon id (resolve via taxon service)
  "occurrenceStatus": "Present",
  "startDate": "2024-06-14",
  "endDate": "2024-06-14",
  "startTime": "09:30",                    // optional
  "site": {                                // one of: existing siteId, or coordinates
    "siteId": 123456,
    "name": "…",
    "coordinates": { "x": 674032, "y": 6580821, "system": "SWEREF99_TM" },
    "accuracy": 25
  },
  "quantity": 3,
  "quantityUnit": "Individuals",
  "activity": "Seen",                      // from a controlled vocabulary
  "lifeStage": "Adult",
  "sex": "Female",
  "determinationMethod": "…",
  "observers": "Frida Merell",
  "reportedBy": "Frida Merell",
  "privateComment": "…",
  "publicComment": "…",
  "unspontaneous": false,
  "protectedBySystem": false,
  "media": [ { "type": "Image", "url": "…" } ],
  "projectId": null,
  "datasetId": null
}
```

Typical operations: `POST` create sighting, `PUT`/`PATCH` update, `DELETE`
remove, `GET` read back — plus lookups for the user's sites/projects. Confirm all
of this against the product's OpenAPI 3 doc; do not ship against these field
names blindly.

## What to build now (before the grant)

- Keep taxon-ID resolution, site/coordinate handling (SWEREF99 TM ↔ WGS84), and
  the reporting **data model** in Tempus independent of the transport.
- `ArtportalenWriteClient` in the bundled script is a stub with the method
  signatures and a clear `ArtportalenAccessError` — fill in the HTTP calls once
  you have the sandbox spec.
- Write integration tests against the sandbox, not production.
- Do not queue real user observations for "send later" until the sandbox
  round-trip is proven.
