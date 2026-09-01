# Inbjudningar

Delbara inbjudningslänkar. En inbjudan kan peka på en **grupp** – ett Verso-hus
eller ett Flux-projekt – och då blir den som löser in den medlem där. Utan mål
ger inbjudan bara ett konto.

- **Status:** implementerad.
- **Bas-URL:** `/api/accounts/invitations/`
- **Autentisering:** sessions-cookie (samma som resten av frontend). Alla
  skrivande anrop kräver `X-CSRFToken`-headern – hämta värdet från
  `GET /api/accounts/csrf/` först och skicka `credentials: "include"`.

En inbjudan är **flergångs**: den konsumeras inte när någon löser in den. Den
gäller tills `expires_at` passeras (default 7 dygn) eller tills en gruppmedlem
återkallar den.

## Datamodell

Som mest ett av `house` / `project` är satt – båda får vara `null`.

| Fält | Typ | Kommentar |
| --- | --- | --- |
| `id` | int | |
| `house` | int \| null | hus-id (Verso). |
| `project` | int \| null | projekt-id (Flux). |
| `target_kind` | `"house"` \| `"project"` \| `"account"` | `"account"` = inget mål, bara konto. |
| `label` | string | valfri fritext, t.ex. "Sommargäster 2026". |
| `created_by` | int \| null | användaren som skapade inbjudan. |
| `created_at` | datetime | |
| `expires_at` | datetime \| null | `null` = ingen utgång. Utelämnas vid create → `now + 7 dygn`. |
| `revoked_at` | datetime \| null | satt när inbjudan återkallats. |
| `uses` | int | antal lyckade inlösen. |
| `last_used_at` | datetime \| null | |
| `is_active` | bool | `true` om varken återkallad eller utgången. |
| `token` | string | **returneras bara i svaret på `POST /`** – aldrig i list/detalj. |

## Skapa en inbjudan

Anger du `house` eller `project` måste du vara medlem där.

```http
POST /api/accounts/invitations/
Content-Type: application/json
X-CSRFToken: <token>

{ "house": 3, "label": "Sommargäster 2026" }
```

```http
{ "project": 8, "label": "Konsulter", "expires_at": null }
```

```http
{ "label": "Allmän inbjudan" }
```

Skicka som mest ett av `house` / `project` – utelämna båda för en inbjudan som
bara skapar ett konto. `label` och `expires_at` är valfria. `"expires_at": null`
ger en länk som aldrig går ut.

`201 Created`:

```json
{
  "id": 12,
  "house": 3,
  "project": null,
  "target_kind": "house",
  "label": "Sommargäster 2026",
  "created_by": 4,
  "created_at": "2026-09-01T09:00:00Z",
  "expires_at": "2026-09-08T09:00:00Z",
  "revoked_at": null,
  "uses": 0,
  "last_used_at": null,
  "is_active": true,
  "token": "Q1v...redacted...9kZ"
}
```

Bygg inbjudningslänken av `token`, t.ex. `https://app.example.se/join?token=<token>`.
`token` går inte att hämta igen – visa eller kopiera den direkt. Skapa en ny
inbjudan om den tappas bort.

`400` om användaren inte är medlem i den angivna gruppen, eller om både `house`
och `project` skickas.

## Lista och läsa

```http
GET /api/accounts/invitations/
GET /api/accounts/invitations/?house=3
GET /api/accounts/invitations/?project=8
GET /api/accounts/invitations/{id}/
```

Returnerar inbjudningar för hus och projekt där den inloggade användaren är
medlem, samt mållösa inbjudningar som användaren själv skapat. `token` utelämnas.
Både aktiva och inaktiva rader ingår – filtrera på `is_active` i frontend.

## Återkalla

```http
DELETE /api/accounts/invitations/{id}/          → 204 No Content
POST   /api/accounts/invitations/{id}/revoke/    → 200, hela objektet
```

Båda sätter `revoked_at` och raderar inte raden. Kräver medlemskap i gruppen.

## Lösa in en inbjudan

```http
POST /api/accounts/invitations/redeem/
```

Öppet endpoint (kräver ingen inloggning), men CSRF-headern krävs ändå.

### Redan inloggad användare

```json
{ "token": "Q1v...9kZ" }
```

`200 OK`:

```json
{ "target_kind": "house", "target": { "id": 3, "name": "Torpet" }, "created": false }
```

Användaren läggs till som medlem i gruppen (idempotent). För en mållös inbjudan
blir svaret `{ "target_kind": "account", "target": null, "created": false }` och
inget medlemskap ändras.

### Anonym besökare – skapar konto

```json
{
  "token": "Q1v...9kZ",
  "username": "nykund",
  "password": "ett-starkt-lösenord",
  "email": "ny@example.se"
}
```

`username` och `password` krävs när anropet är oautentiserat. `email` är valfri.
Lösenordet valideras med Djangos lösenordsregler. Vid lyckat anrop skapas kontot,
användaren loggas in (sessions-cookie sätts i svaret) och läggs till i gruppen.

`200 OK`:

```json
{ "target_kind": "project", "target": { "id": 8, "name": "Ombyggnad" }, "created": true }
```

### Felfall

| Status | Kropp | Orsak |
| --- | --- | --- |
| `400` | `{"token": [...]}` | ogiltig, utgången eller återkallad token. |
| `400` | `{"username": [...]}` | användarnamnet är upptaget. |
| `400` | `{"password": [...]}` | lösenordet uppfyller inte kraven. |
| `400` | `["Provide username and password ..."]` | anonymt anrop utan `username`/`password`. |
| `400` | `["An invitation can target at most one ..."]` | både `house` och `project` skickades vid create. |

## Frontend-flöde

Alla anrop går mot API-domänen med `credentials: "include"`. Skrivande anrop
kräver `X-CSRFToken`. Hjälpare:

```js
const API = "https://origo.api.origo.test"; // byt per miljö

let _csrf = null;
async function csrf() {
  if (_csrf) return _csrf;
  const r = await fetch(`${API}/api/accounts/csrf/`, { credentials: "include" });
  _csrf = (await r.json()).csrfToken;
  return _csrf;
}

async function api(path, { method = "GET", body } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (method !== "GET") headers["X-CSRFToken"] = await csrf();
  const r = await fetch(`${API}${path}`, {
    method,
    headers,
    credentials: "include",
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = r.status === 204 ? null : await r.json();
  if (!r.ok) throw Object.assign(new Error("api"), { status: r.status, data });
  return data;
}
```

### 1. Skapa en inbjudan

```js
// Till ett hus:      { house: houseId, label }
// Till ett projekt:  { project: projectId, label }
// Bara konto:        { label }              (utelämna house och project)
const inv = await api("/api/accounts/invitations/", {
  method: "POST",
  body: { project: projectId, label: "Konsulter" },
});

const link = `${window.location.origin}/join?token=${encodeURIComponent(inv.token)}`;
// Visa `link` med en kopiera-knapp + texten "Länken visas bara en gång".
```

`inv.token` finns bara i det här svaret. Vid `err.status === 400` är användaren
inte medlem i gruppen, eller så skickades både `house` och `project`.

### 2. Hantera inbjudningar

```js
const list = await api(`/api/accounts/invitations/?house=${houseId}`);
// eller ?project=<id>, eller utan filter (inkl. egna mållösa inbjudningar)
// visa: label, target_kind, expires_at, uses, is_active
```

Återkalla:

```js
await api(`/api/accounts/invitations/${id}/revoke/`, { method: "POST" });
// eller: api(`/api/accounts/invitations/${id}/`, { method: "DELETE" })
```

Filtrera bort `is_active === false` i listan om bara giltiga länkar ska visas.

### 3. Landningssida `/join?token=…`

```js
const token = new URLSearchParams(location.search).get("token");

// Är besökaren inloggad?
let me = null;
try { me = await api("/api/accounts/me/"); } catch (e) { /* 401 → ej inloggad */ }

function landing(res) {
  // res = { target_kind, target, created }
  if (res.target_kind === "house") location.href = `/houses/${res.target.id}`;
  else if (res.target_kind === "project") location.href = `/projects/${res.target.id}`;
  else location.href = "/";           // target_kind === "account" → inget mål
}

if (me) {
  // Visa "Gå med"-knapp:
  try {
    landing(await api("/api/accounts/invitations/redeem/", {
      method: "POST",
      body: { token },
    }));
  } catch (e) {
    if (e.status === 400) showError("Inbjudan är inte längre giltig.");
  }
} else {
  // Visa registreringsformulär (username, password, email):
  try {
    // created === true, sessions-cookie satt → besökaren är inloggad
    landing(await api("/api/accounts/invitations/redeem/", {
      method: "POST",
      body: { token, username, password, email },
    }));
  } catch (e) {
    if (e.status === 400) {
      // e.data.token / e.data.username / e.data.password – visa vid rätt fält
    }
  }
}
```

**Nästa.js:** kör `/join`-logiken i en client component (`"use client"`), och
sätt `credentials: "include"` + rätt `API`-origin. Efter lyckad `redeem` med
`created: true` behöver du inte logga in separat – cookien är redan satt.
