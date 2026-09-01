# Accounts

`accounts` is the shared identity app for every Origo product. It provides the
custom `User` model, session/CSRF endpoints, DRF auth tokens, cross-product
user lookup, in-app notifications, and shareable invitation links.

Base prefix: `/api/accounts/`.

- **Status:** implemented.
- **Primary authentication:** shared cross-subdomain session cookie. Writing
  calls need the `X-CSRFToken` header — fetch it from `GET /api/accounts/csrf/`
  first and send every request with `credentials: "include"`.
- **Token authentication:** a DRF `Token` can be issued for non-browser clients
  (BirdNET devices, the external observation client). See
  [Tokens](#tokens).

## Session and identity endpoints

| Path | Method | Purpose |
|---|---|---|
| `csrf/` | GET | Set the CSRF cookie and return `{ "csrfToken": ... }`. |
| `login/` | POST | `{ "username", "password" }`; sets the session cookie, returns `204`. |
| `logout/` | POST | Clears the session, returns `204`. |
| `me/` | GET | The current user (`id`, `username`, `email`, `first_name`, `last_name`, `open_notifications`). |
| `self/{id}/` | GET/PUT/PATCH | Read or update the current user's own row (the queryset only ever contains the caller). |
| `self/set-password/` | POST | `{ "current_password", "new_password" }`; validates against Django's password rules, keeps the session signed in, returns `204`. |

## Tokens

For clients that cannot hold a browser session.

| Path | Method | Purpose |
|---|---|---|
| `token/` | POST | `{ "username", "password" }` → `{ "token": ... }` (DRF `obtain_auth_token`). |
| `self/token/` | GET or POST | Return the current user's token, creating it if needed. |
| `self/token/?rotate=1` | POST | Delete and re-create the token, returning the new value. |
| `self/token/` | DELETE | Revoke the current user's token, returns `204`. |

Send the token as `Authorization: Token <key>`. Treat it as a secret and never
log it. Rotating or revoking a token immediately invalidates every client
still using the old value.

## Users

`GET /api/accounts/users/` — read-only, paginated. Returns users who share a
Flux project or Verso house with the requester (the requester is excluded).
Filters: `id`, `username`, `email`. Each row carries `open_notifications`, the
recipient's unread-notification count.

## Notifications

`GET /api/accounts/notifications/` — the current user's notifications, newest
first. Read-only rows; only the read-state actions below mutate them.

| Path | Method | Purpose |
|---|---|---|
| `notifications/` | GET | List; filters `domain`, `is_read`, and `unread=true`. |
| `notifications/{id}/` | GET | One notification. |
| `notifications/summary/` | GET | `{ "unread_count", "latest": [...] }` (latest 10). Poll about once a minute. |
| `notifications/{id}/read/` | POST | Mark one as read; returns the row. |
| `notifications/read-all/` | POST | Mark all unread as read; returns `{ "marked_read": <count> }`. |

The Tempus season digest is delivered here — see
[Tempus phenograms](../tempus/phenograms.md).

## Invitations

Shareable multi-use invite links for Verso houses and Flux projects. See
[Inbjudningar](invitations.md).
