# Frontend handoff: Flux app design, scaffolding and visual identity

## Scope

This covers everything added to Flux for taking a project from idea to
generated code: the structured data model (entities, fields, relations), the
rest of the app design (stack, API resources, roles, screens, integrations,
seed data), code generation, and **shared visual identities** that a project
can opt in to.

It does **not** cover the Codex/MCP surface (`/api/flux/codex/…`); that is for
agents, not the web app.

Suggested placement: a new section, `/flux/model`, with its own data fetching in
the section layout. Do not add this data to `FluxProviders`; the board endpoint
(`GET /api/flux/projects/{id}/board/`) is unchanged apart from the two new
project fields below.

Backend prerequisites: the migrations for the new models must be applied.

## Conventions (same as the rest of Flux)

- Base path `/api/flux/`, session auth, CSRF token on non-GET requests.
- Every list is a plain array (no pagination).
- Everything is scoped to projects the user is a member of. A resource you
  cannot see answers `404` on detail routes and is simply absent from lists.
- Validation errors are `400` with DRF's shape: `{"field": ["message"]}`, or
  `{"detail": "message"}` for action endpoints.
- Filters are query parameters, e.g. `?project=3`.
- Foreign keys are numeric ids.

## Project: opting in to an identity

Two new fields on the existing project resource (`/projects/`, and inside the
board response):

| Field | Type | Notes |
|---|---|---|
| `include_identity` | boolean, default `false` | The per-project switch. |
| `identity` | id or `null` | The chosen shared identity. |

Rules enforced by the backend:

- Turning `include_identity` off clears `identity` (send only the switch; you
  do not need to null the id).
- Sending an `identity` while the switch is off is ignored (`identity` comes
  back `null`).
- You may only *choose* an identity you own. Keeping the one the project
  already has is always allowed, whoever owns it.

**UI rule:** identity UI exists only where it is relevant. The switch itself
lives in project settings, off by default. Show the identity picker, the
"Identity" tab and the `design` scaffold target **only when
`project.include_identity` is true**. The backend refuses `target=design`
otherwise (`400`).

## Identities (shared)

`/identities/`: a brand profile owned by one user and reusable by many
projects. Origo has several looks and other projects have entirely different
ones, so a project picks one instead of copying it.

- `GET /identities/`: identities you own **plus** those used by projects you are
  a member of. Filters: `?id=`, `?name=`.
- `POST /identities/`: creates one; you become `owner`.
- `PATCH`/`DELETE`: **owner only** (others get `404`). Deleting an identity
  leaves projects intact with `identity: null` (and `include_identity` still
  `true`, so show the "choose an identity" empty state).
- The picker should offer identities where `owner === currentUser.id`, plus the
  project's current one. Choosing anyone else's returns `400`.
- Show non-owners a read-only view (`owner !== currentUser.id`).
- The response has no usage count, so a delete warning cannot say how many
  projects use it.

```ts
type Identity = {
  id: number;
  owner: number;                     // read-only
  name: string;                      // unique per owner
  description: string;
  brand_name: string;
  tagline: string;
  tone: string;                      // tone of voice for copy
  theme_modes: "light" | "dark" | "both";   // default "both"
  default_mode: "system" | "light" | "dark"; // only used when theme_modes is "both"
  colors: IdentityColor[];
  heading_font: string;
  body_font: string;
  mono_font: string;
  font_import_url: string;           // https:// stylesheet, or ""
  font_weights: number[];            // 100..900 in steps of 100, default [400, 600, 700]
  base_font_size: number;            // px, 8..32, default 16
  type_scale_ratio: string;          // DRF Decimal => STRING, e.g. "1.250"; 1..2
  spacing_unit: number;              // px, 1..16, default 4
  radii: Record<string, number>;     // name -> px, default {sm:4, md:8, lg:16}
  shadows: Record<string, string>;   // name -> CSS box-shadow value
  shadows_dark: Record<string, string>; // dark-mode overrides of `shadows`, by name
  assets: IdentityAsset[];
  logo_rules: string;
  icon_library: string;              // e.g. "lucide"
  icon_style: string;                // e.g. "outline"
  accessibility_target: "AA" | "AAA";
  guidelines: string;                // free markdown
  created_at: string;
  updated_at: string;
}

type IdentityColor = {
  name: string;                      // unique (case-insensitive) within the identity
  role: ColorRole | "";
  light: string;                     // "#rrggbb"; required unless theme_modes is "dark", else may be ""
  dark: string;                      // "#rrggbb"; required unless theme_modes is "light", else may be ""
}
type ColorRole = "primary" | "secondary" | "accent" | "background" | "surface"
  | "text" | "muted" | "border" | "success" | "warning" | "danger";

type IdentityAsset = {
  name: string;
  kind: "logo" | "logo_mark" | "icon" | "favicon" | "illustration" | "other";
  mode: "any" | "light" | "dark";    // background it is for; default "any"
  url: string;                       // https:// or root-relative "/…"
  usage: string;
}
```

Validation to mirror in the form (the server is the source of truth and
answers `400` per field):

- Colors: `#RRGGBB` only (no 3-digit hex, no names). Stored lowercase.
- Which colour values are required follows `theme_modes`: `both` needs a
  `light` **and** a `dark` value for every colour, `light` needs only `light`,
  `dark` needs only `dark`. The check runs on the whole identity, so changing
  `theme_modes` re-validates the existing colours: switching to `both` on an
  identity without dark values is a `400` on `colors` unless you send the dark
  values in the same request. Values for a mode the identity does not support
  are ignored by the generator.
- `default_mode` only matters for `both`. `assets[].mode` is `any`, `light` or
  `dark`; `shadows_dark` uses the same rules as `shadows`.
- Font names: letters, digits, spaces, `-` and `_` only (they are placed inside
  quotes in CSS). `font_import_url`: `https://` or `/…`, no spaces or quotes.
- `radii` and `shadows` keys: lowercase words joined by `-`. Shadow values are
  plain `box-shadow` values (no `;`, `{`, `}`, `url(`, comments).
- `assets[].url`: `https://` or root-relative, no spaces or quotes.
- `(owner, name)` is unique: `400` on `name`.

### Editor

Group the form like the generated style guide: Brand, Themes, Colors,
Typography, Shape, Logo and icons, Guidelines.

- **Themes:** a "Light / Dark / Light and dark" choice (`theme_modes`), and for
  "Light and dark" a default (`default_mode`: follows the system / light /
  dark). Show only the colour columns the choice needs, and an inline hint when
  a required value is missing (the server rejects it).
- **Colors:** a table with name, role, and a light and/or dark value per the
  chosen theme. Offer the role list above; contrast checks work on roles, so
  encourage at least `text`, `background`, `surface`, `primary`.
- **Logo and icons:** give each asset a mode. A logo that only works on a light
  background should be `light`; provide a `dark` counterpart for dark
  backgrounds. When rendering a logo, pick the asset whose `mode` matches the
  current theme, falling back to `any`.
- **Shadows:** `shadows_dark` is optional; add a dark override only where a
  shadow should differ (dark surfaces usually need a heavier shadow).
- **Contrast preview** (do it client-side, live). WCAG relative luminance,
  ratio = `(L1 + 0.05) / (L2 + 0.05)` with the lighter colour first. The
  backend checks these pairs for each supported mode (`light`, `dark` or both,
  following `theme_modes`):

  | Pair | AA | AAA |
  |---|---|---|
  | `text` on `background`, `text` on `surface`, `muted` on `background` | 4.5 | 7 |
  | `primary` on `background`, `accent` on `background` | 3 | 4.5 |

  The generated `STYLEGUIDE.md` prints the same table, so the UI and the file
  agree.
- **Live preview:** render a sample card inside a container whose inline style
  sets the `--brand-*` variables described below; do not touch the app's own
  theme. For "Light and dark" give the preview a light/dark toggle, and show
  the contrast table for the mode being previewed.
- Type scale for the preview: step size (rem) = `(base_font_size / 16) *
  ratio ** n` for `xs=-2, sm=-1, base=0, lg=1, xl=2, 2xl=3, 3xl=4, 4xl=5`.

## Generated files

```http
GET /projects/{id}/scaffold/?target=design
```

```json
{"target": "design", "files": [{"path": "identity/tokens.css", "content": "…"}]}
```

`target=design` returns (`assets.ts` only when the identity has assets, an icon
library or logo rules):

| File | Purpose |
|---|---|
| `identity/fonts.css` | `@import` of `font_import_url` plus `--brand-font-*` |
| `identity/tokens.css` | `--brand-*` colours, type sizes, spacing, radii, shadows, plus `color-scheme`; how the modes are wired depends on `theme_modes` and `default_mode` (below) |
| `identity/tailwind.theme.css` | Tailwind v4 `@theme inline` block mapping utilities to the variables |
| `identity/tailwind.theme.ts` | Object for `tailwind.config.ts` `theme.extend` |
| `identity/tokens.ts` | The same values as a typed constant |
| `identity/assets.ts` | Logo/icon manifest |
| `identity/STYLEGUIDE.md` | Human-readable instructions and contrast results |

How the modes are emitted in `tokens.css`:

| `theme_modes` | `default_mode` | Result |
|---|---|---|
| `light` | (ignored) | `:root` holds the light values, `color-scheme: light`. No dark. |
| `dark` | (ignored) | `:root` holds the dark values, `color-scheme: dark`. No light. |
| `both` | `system` | Light on `:root`; dark under `prefers-color-scheme: dark` unless `<html data-theme="light">`; `data-theme="dark"` forces dark. |
| `both` | `light` | Light on `:root`; dark only with `<html data-theme="dark">`. The OS setting is ignored. |
| `both` | `dark` | Dark on `:root`; light only with `<html data-theme="light">`. |

So the app's theme toggle just sets `data-theme` on `<html>` (`light` or
`dark`); remove the attribute to fall back to the identity's default. For
`both` with a `light`/`dark` default, `tailwind.theme.css` also declares
`@custom-variant dark` keyed to `data-theme="dark"`, so `dark:` utilities follow
the toggle. With `system` the variant is not overridden; prefer the variables
over `dark:` utilities.

The variables are `--brand-<colour-name-slug>`, `--brand-font-{heading,body,mono}`,
`--brand-text-{xs..4xl}`, `--brand-space-{1,2,3,4,5,6,8,10,12,16}` (multiples
of `--brand-space-unit`), `--brand-radius-<name>`,
`--brand-shadow-<name>`. Tailwind utilities go through them, so dark mode keeps
switching (`bg-primary`, `text-text`, `font-heading`, `rounded-md`, …).

Applying it in a Tailwind v4 app (order matters; the font `@import` must come
first):

```css
@import "tailwindcss";
@import "./identity/fonts.css";
@import "./identity/tokens.css";
@import "./identity/tailwind.theme.css";
```

Show the result as a file tree with a preview pane and copy/download. The
backend writes nothing to disk.

## Scaffold and planning actions

```http
GET  /projects/{id}/scaffold/?target=django|typescript|csharp|skeleton|design
POST /projects/{id}/scaffold-document/    {"target": "django"}
POST /projects/{id}/generate-tasks/
```

- `scaffold` returns `{"target", "files": [{"path", "content"}]}`. Unknown
  target, an unsupported default value, or `design` without an identity answers
  `400 {"detail": "…"}`; show the message.
- `scaffold-document` saves the result as a markdown document named
  `Scaffold: <target>` and updates it on later calls. Returns the document, so
  refetch or merge it into the documents in context.
- `generate-tasks` creates standard milestones and tasks from the design
  (data model, API, permissions, screens, tests, and an `Identitet: <name>` task
  only when the project includes an identity). It never duplicates existing
  ones and answers `201 {"created": [{"id", "title", "milestone"}]}`, possibly
  an empty list. Refetch milestones and tasks afterwards.
- Targets: `django`, `typescript` and `csharp` are only useful once the project
  has entities (with none they return near-empty files); `skeleton` is always
  available; `design` needs an identity.

## Design resources

Everything below is standard CRUD (`GET` list, `POST`, `GET/PATCH/DELETE {id}/`).
Filters are the only query parameters.

| Path | Filters | Body fields |
|---|---|---|
| `/entities/` | `project` | `project`, `name`, `description` |
| `/fields/` | `entity`, `entity__project` | `entity`, `name`, `type`, `description`, `nullable`, `unique`, `default`, `max_length`, `order` |
| `/relations/` | `source`, `target`, `source__project` | `source`, `target`, `kind`, `name`, `related_name`, `on_delete`, `nullable`, `description` |
| `/stack-profiles/` | `project` | `project`, `targets`, `api_naming`, `auth_method`, `database`, `app_label`, `namespace` |
| `/resources/` | `entity`, `entity__project` | `entity`, `path`, `operations`, `filters`, `ordering` |
| `/roles/` | `project` | `project`, `name`, `description` |
| `/role-permissions/` | `role`, `resource`, `role__project` | `role`, `resource`, `operation`, `scope` |
| `/screens/` | `project`, `parent` | `project`, `name`, `route`, `description`, `entities` (ids), `parent` |
| `/integrations/` | `project`, `kind` | `project`, `name`, `kind`, `description`, `env_vars` (string[]) |
| `/seed-rows/` | `entity`, `entity__project` | `entity`, `data` (object), `order` |

Enums:

- `Field.type`: `string`, `text`, `int`, `bigint`, `decimal`, `float`, `bool`,
  `date`, `datetime`, `time`, `uuid`, `json`, `email`, `url`.
- `Relation.kind`: `fk`, `m2m`, `o2o`. `on_delete`: `cascade`, `protect`,
  `set_null`.
- `StackProfile.targets` (array): `django`, `typescript`, `csharp`.
  `api_naming`: `snake_case`, `camel_case`. `auth_method`: `session`, `token`,
  `jwt`, `none`. `database`: `postgresql`, `mysql`, `sqlite`, `sqlserver`.
- `Resource.operations` (array): `list`, `retrieve`, `create`, `update`,
  `delete`. `RolePermission.operation` uses the same values; `scope`: `all`,
  `own`, `member`.
- `Integration.kind`: `api`, `auth`, `storage`, `email`, `payment`, `other`.

Rules that surface as `400`:

- Names are unique where it matters: entity name per project, field name per
  entity, relation name per source entity, role name per project, screen
  `route` per project, integration name per project, and one permission per
  `(role, resource, operation)`.
- A relation name may not equal a field name on the same entity, and vice versa.
- Relation `source` and `target` must be in the same project. A permission's
  resource must be in the role's project. A screen's `parent` and `entities`
  must be in the screen's project (and a screen cannot be its own parent).
- `StackProfile` is one per project (`POST` once, then `PATCH`).
- A resource is one per entity (`OneToOne`); create it from the entity view.
- `seed-rows.data` keys must be fields, relations or `id` of that entity.
- Defaults are strings on the wire (e.g. `"100"`, `"false"`, `"now"`,
  `"uuid4"`). Unsupported combinations are reported by `scaffold`, not on save.

## Suggested screens

This maps to the frontend tasks already in Flux (project "Origo Flux",
milestone "Kickstarta nya projekt från datamodell", tasks 169-177):

| Phase | Screen | Endpoints |
|---|---|---|
| 0 | Entities list with detail panel, field/relation drawers, ER diagram | `entities`, `fields`, `relations` |
| 1 | Stack settings form | `stack-profiles` |
| 2 | Code generation: target picker, file tree, preview, copy, "save as document" | `scaffold`, `scaffold-document` |
| 3 | Resource tab on an entity | `resources` |
| 4 | Roles and permission matrix (resource × operation, scope) | `roles`, `role-permissions` |
| 5 | "Generate tasks" with a result summary | `generate-tasks` |
| 6 | Screen tree | `screens` |
| 7 | Seed data, integrations, decision documents | `seed-rows`, `integrations`, documents with `kind: "decision"` |
| Identity | Project switch, identity picker, identity library and editor, `design` target | project, `identities`, `scaffold` |

Notes:

- `Document.kind` gained `decision` (in addition to `markdown`, `flowchart`,
  `database_schema`).
- The permission matrix is easiest to build from `resources` (rows) and
  `role-permissions` filtered by `role__project`.
- The ER diagram can be drawn straight from `entities`, `fields` and
  `relations` (`?…project=` filters); there is no diagram endpoint.
- Generated `django`/`typescript`/`csharp` code can be checked into the user's
  repo, but the app itself only shows and downloads it.
