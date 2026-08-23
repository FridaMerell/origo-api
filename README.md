# Origo

Origo is a Django API that serves as the shared backend for multiple apps:

- **Flux** — project management
- **Oikos** — house maintenance

A separate Next.js monorepo provides the frontends for both apps, served on
their own subdomains, and stays signed in across both via a shared Django
session cookie.

## App structure

- `accounts` — common ground shared by every app: a custom `User` model
  (`AUTH_USER_MODEL = 'accounts.User'`) and Django's built-in `Group` model.
- `flux` — project management, mounted at `/api/flux/`.
- `oikos` — house maintenance, mounted at `/api/oikos/`.

The API is built with Django REST Framework, authenticated via DRF's
`SessionAuthentication` so the frontend's session cookie authenticates API
calls directly.

## Cross-subdomain sessions

Flux and Oikos frontends are expected to live on subdomains of one root
domain (e.g. `flux.<root-domain>`, `oikos.<root-domain>`), with the API on
its own subdomain. The session cookie is scoped to the shared root domain via
`SESSION_COOKIE_DOMAIN` so it's readable across subdomains. The root domain
defaults to `origo.test` for local development and can be overridden with the
`ROOT_DOMAIN` environment variable once real domains are chosen.

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
