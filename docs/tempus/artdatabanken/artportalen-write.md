# Reporting observations to Artportalen

## Current status

Tempus cannot currently report observations to Artportalen. SOS is read-only.
Writing requires the separate **Artportalen – Species Observations Read and
Write** product, and access has not been granted.

No production reporting client, queue, or synchronization state should be
implemented as though access already exists.

## Access required

Request sandbox access through the Artdatabanken developer portal or SLU
support. Describe Tempus, expected volume, user workflow, and intended data.
Approval should provide:

- sandbox and production base URLs;
- product subscription key;
- OAuth client credentials and redirect URI;
- exact write scope;
- current OpenAPI document; and
- rules for sites, projects, media, protected observations, and consent.

This is separate from SOS, Dyntaxa, and Artfakta subscriptions.

## Expected authentication

```http
Ocp-Apim-Subscription-Key: <write-product-key>
Authorization: Bearer <user-access-token>
```

Writes are made as an Artportalen user. The expected web flow is Authorization
Code with PKCE. Do not use unattended credentials unless SLU explicitly
provisions and permits them.

## Future reporting boundary

Keep Tempus observations independent of the external transport. A future
adapter should translate a validated internal DTO into the exact granted API
schema. Likely information categories are:

- accepted Dyntaxa taxon ID and presence status;
- date/time interval;
- existing site or coordinates, accuracy, and coordinate system;
- quantity and unit;
- activity, life stage, sex, and determination method;
- observers/reporter and public/private comments;
- project/dataset association and media metadata.

These are design categories, not confirmed field names. The granted OpenAPI
document defines endpoints, required fields, enumerations, and combinations.

## Safe implementation sequence

1. Obtain sandbox access and authoritative specification.
2. Implement OAuth consent, secure token storage, refresh, and revocation.
3. Add a transport-independent report DTO with explicit validation.
4. Implement a sandbox-only client with idempotency and structured errors.
5. Test create, read-back, update, and delete round trips.
6. Define user-visible draft/submitting/accepted/rejected states.
7. Complete privacy and protected-species review.
8. Enable production only after explicit operational approval.

Do not queue real observations for later submission until sandbox round trips,
identity mapping, retries, duplicate handling, and consent are proven.

