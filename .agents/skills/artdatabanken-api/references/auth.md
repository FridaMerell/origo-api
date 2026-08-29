# Authentication

## 1. Subscription keys (always required)

Register at <https://api-portal.artdatabanken.se/>, then subscribe to each
product you need. Each subscription exposes a **primary** and **secondary** key
(rotate by swapping). Send it on every request:

```
Ocp-Apim-Subscription-Key: <key>
```

It may also be passed as `?subscription-key=<key>`, but the header is preferred
(query strings leak into logs). The header is checked first.

Products and their keys used here:

| Env var | Product to subscribe to |
|---|---|
| `ARTDATABANKEN_SOS_KEY` | Species Observations – multiple data resources |
| `ARTDATABANKEN_TAXON_KEY` | Taxonomy (covers Dyntaxa Taxon Service + Taxon List Service) |
| `ARTDATABANKEN_ARTFAKTA_KEY` | Artfakta – Species Information (optional) |
| `ARTPORTALEN_WRITE_KEY` | Artportalen – Species Observations Read and Write (only once granted) |

For SOS and taxonomy, the subscription key alone authorizes all **public** data.

## 2. OAuth 2.0 bearer token (only for protected data + the write API)

Needed for:
- SOS sensitive/protected observations (exact coordinates of protected taxa).
- Every call to the Artportalen Read+Write API.

Standard: OAuth 2.0 + OpenID Connect, **Authorization Code grant with PKCE**
([RFC 7636](https://datatracker.ietf.org/doc/html/rfc7636)).

Issuer: `https://ids.artdatabanken.se` (older SOS docs reference
`https://useradmin-auth.slu.se` — confirm the current issuer, authorize and
token paths from the portal / the product's OpenAPI doc before coding).

Typical endpoints:
- Authorize: `<issuer>/connect/authorize`
- Token: `<issuer>/connect/token`

You need from SLU support:
- `client_id` + `client_secret`
- a registered redirect URI
- the scopes (SOS protected: `SOS.Observations.Protected`; write API scope is
  assigned on grant)

### Flow (server-side web app)

1. Redirect the user to `authorize` with `response_type=code`,
   `code_challenge` (S256), `scope`, `redirect_uri`, `state`.
2. Receive `code` at the redirect URI.
3. POST to `token` with `grant_type=authorization_code`, `code`,
   `code_verifier`, `redirect_uri`, client credentials → `access_token`
   (+ `refresh_token`).
4. Send `Authorization: Bearer <access_token>` alongside the subscription key.
5. Refresh with `grant_type=refresh_token` before expiry.

For unattended jobs, ask SLU whether `client_credentials` is permitted for your
client; if so, skip the user redirect and just POST client creds + scope to the
token endpoint.

### Token caching

Cache the access token in memory (or Django cache) keyed by scope, refresh ~60s
before `expires_in`. The bundled client accepts
`oauth_token_provider: Callable[[], str]` — supply a function that returns a
valid token; the client never does the redirect dance itself.

## 3. Django wiring

`settings.py`:

```python
import os

ARTDATABANKEN = {
    "SOS_KEY": os.environ["ARTDATABANKEN_SOS_KEY"],
    "TAXON_KEY": os.environ["ARTDATABANKEN_TAXON_KEY"],
    "ARTFAKTA_KEY": os.environ.get("ARTDATABANKEN_ARTFAKTA_KEY"),
    "WRITE_KEY": os.environ.get("ARTPORTALEN_WRITE_KEY"),
    "USER_AGENT": "Tempus/1.0 (frida.merell@gmail.com)",
}
```

Build the client in a small factory (e.g. `tempus/services/artdatabanken.py`)
so views/tasks get a configured instance and tests can inject a fake.

Add the new env vars to `.env.example`.
