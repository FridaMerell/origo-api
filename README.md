# Origo

Origo is a Django API that serves as the shared backend for multiple apps:

- **Flux** — project management
- **Verso** — house maintenance
- **Apsis** — public posts
- **Tempus** — species following, seasonality (phenograms), observations,
  nature routes, and short-lived BirdNET detections

A separate Next.js monorepo provides the frontends for these apps, served on
their own subdomains, and stays signed in across them via a shared Django
session cookie.

Feature and API documentation lives in [`docs/`](docs/README.md).

## App structure

- `accounts` — common ground shared by every app: a custom `User` model
  (`AUTH_USER_MODEL = 'accounts.User'`) and Django's built-in `Group` model.
- `flux` — project management, mounted at `/api/flux/`.
- `verso` — house maintenance, mounted at `/api/verso/`.
- `apsis` — public posts, mounted at `/api/apsis/`.
- `tempus` — species, seasonality, observations, routes, and BirdNET, mounted
  at `/api/tempus/` (BirdNET ingest/stream at `/api/birdnet/`).

The API is built with Django REST Framework, authenticated via DRF's
`SessionAuthentication` so the frontend's session cookie authenticates API
calls directly. `TokenAuthentication` is also enabled for non-browser clients
such as BirdNET field devices; tokens are issued under `/api/accounts/`.

## Cross-subdomain sessions

The Flux, Verso, and Apsis frontends are expected to live on subdomains of one
root domain (for example, `flux.<root-domain>`), with the API on its own
subdomain. The session cookie is scoped to the shared root domain via
`SESSION_COOKIE_DOMAIN` so it is sent to the relevant subdomains. The root
domain defaults to `origo.test` and can be overridden with `ROOT_DOMAIN`.

The frontend subdomains and permitted origins are derived from `DOMAINS`,
`FRONTEND_SUBDOMAINS`, and the optional CORS/CSRF overrides. See
[Operations and configuration](docs/tempus/operations.md) for the complete
runtime configuration reference.

## Requirements

- Python 3.x
- Django 6.1
- See `requirements.txt` for full dependencies (Django REST Framework,
  django-cors-headers)

## Getting started

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```
