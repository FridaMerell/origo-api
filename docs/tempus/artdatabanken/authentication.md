# Authentication and configuration

## Subscription keys

Each API product has its own key. Public SOS, Dyntaxa, and Artfakta requests
send `Ocp-Apim-Subscription-Key` as a header. Never place keys in source code,
documentation, URLs, or logs.

| Environment variable | Purpose |
|---|---|
| `ARTDATABANKEN_SUBSCRIPTION_KEY_SOS` | SOS observation access |
| `ARTDATABANKEN_SUBSCRIPTION_KEY_TAXON` | Dyntaxa taxonomy access |
| `ARTDATABANKEN_SUBSCRIPTION_KEY_SPECIES_INFORMATION` | Optional Artfakta access |
| `ARTDATABANKEN_SPECIES_OBSERVATION_URL` | Override SOS base URL |
| `ARTDATABANKEN_TAXON_SERVICE_URL` | Override Dyntaxa base URL |
| `ARTDATABANKEN_SPECIES_INFORMATION_URL` | Override Artfakta base URL |
| `ARTDATABANKEN_TIMEOUT` | General timeout; default 30 seconds |
| `ARTDATABANKEN_PHENOGRAM_TIMEOUT` | SOS phenogram timeout; default 60 seconds |
| `ARTDATABANKEN_COOLDOWN_SECONDS` | Interval between request starts; default 1 second |
| `ARTDATABANKEN_COOLDOWN_STATE_FILE` | Optional shared cooldown state path |
| `ARTDATABANKEN_USER_AGENT` | Descriptive request user agent |
| `ARTDATABANKEN_SPECIESDATA_LANDSCAPES_PATH` | Landscape dataset path |
| `ARTDATABANKEN_SPECIESDATA_BIOTOPES_PATH` | Biotope dataset path |

The service coordinates request starts between local web and worker processes
with a shared lock and cooldown file.

## OAuth

OAuth is not implemented in the current adapter. It is required for exact
protected SOS observations and all Artportalen write operations. The expected
flow is OAuth 2.0 Authorization Code with PKCE against the issuer assigned by
SLU, currently documented as `https://ids.artdatabanken.se`.

Protected calls require both subscription key and bearer token. Confirm issuer,
paths, scopes, redirect URI, and token lifetime against the product's current
portal/OpenAPI documentation. Exact protected coordinates must never be logged
or stored without explicit authorization and a data-protection design.

