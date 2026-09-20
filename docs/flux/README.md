# Flux documentation

Flux is the project-management API mounted at `/api/flux/`.

People are added to a project either directly or through a shareable invite
link — see [Inbjudningar](../accounts/invitations.md).

## API resources

- `projects` — projects and the project board action
- `milestones` — project milestones
- `tags` — reusable, user-owned labels
- `documents` — Markdown and Mermaid documents attached to a project,
  milestone, or task
- `tasks` — tasks, subtasks, dependencies, recurrence, and assignees
- `updates` — project, milestone, and task updates
- `entities`, `fields`, `relations` — the structured data model of a project
- `stack-profiles`, `resources`, `roles`, `role-permissions`, `screens`,
  `integrations`, `integration-operations`, `seed-rows` — the rest of the app
  design; see
  [App design and scaffolding](#app-design-and-scaffolding)
- `identities` — shared visual identities; see
  [Visual identity](#visual-identity)

The web app's view of all this is described in the
[frontend handoff](frontend-handoff.md).

All resources are exposed through Django REST Framework viewsets and
support standard list, retrieve, create, update, and delete actions for
authenticated users scoped to projects they belong to.

Creating a project automatically makes the caller a member. Creation and
updates validate that referenced milestones, tasks, requirements, assignees,
and documents belong to the same project. Task dependency and parent-task
cycles are rejected.

## Filters

### Projects

- `id`
- `members`

Example:

```text
GET /api/flux/projects/?id=1
GET /api/flux/projects/?members=4
```

### Milestones

- `id`
- `project`
- `status`

Example:

```text
GET /api/flux/milestones/?project=1
GET /api/flux/milestones/?status=done
```

### Tags

- `id`
- `name`

Tags are visible when the caller created them or can access a project where
they are used. Only the creating user may retrieve, edit, or delete a tag.

### Documents

- `id`
- `project`
- `milestone`
- `task`
- `kind` (`markdown`, `flowchart`, `database_schema`, or `decision`)

Documents are project-scoped. `milestone` and `task` are optional, but when
provided must belong to `project`. The API records the current user as
`author` when a document is created.

### Tasks

- `id`
- `project`
- `milestone`
- `parent`
- `assignees`
- `priority`
- `recurrence`
- `recurrence_source`

Example:

```text
GET /api/flux/tasks/?project=1&milestone=2
GET /api/flux/tasks/?assignees=4&priority=high
```

Recurring tasks require a due date. Valid recurrence values are `none`,
`daily`, `weekly`, `monthly`, and `yearly`; `recurrence_interval` is at least
one, and `recurrence_end_date` cannot be before the due date. Completing a
recurring task creates its next occurrence when one is due.

Open tasks whose `due_date` is today are processed by the daily
`notify_flux_task_deadlines` background task. Each assignee receives an in-app
`accounts.Notification` in the `flux` domain. When Resend is configured, the
same notification is queued for email delivery. A task is notified at most
once per assignee and day.

### Updates

- `id`
- `project`
- `milestone`
- `task`

Example:

```text
GET /api/flux/updates/?project=1
GET /api/flux/updates/?task=3
```

## Timeline

`GET /api/flux/timeline/` returns all timeline data for every project the
authenticated user can access:

```json
{
  "projects": [],
  "milestones": [],
  "tasks": [],
  "updates": [],
  "documents": [],
  "users": []
}
```

The `users` collection includes project members, task assignees, and authors
of updates and documents referenced by the returned data.

## Relationship notes

- Projects are scoped to the authenticated user's memberships.
- Milestones are scoped through their parent project.
- Tasks are scoped through their parent project and can be filtered by parent
  task, assignee, milestone, recurrence source, and priority.
- Updates are scoped through their parent project and can be filtered by
  project, milestone, or task.
- `GET /api/flux/projects/{id}/board/` returns the selected project together
  with accessible projects, milestones, tasks, updates, documents, and the
  users relevant to that board.
- File metadata is stored as a JSON list on projects, milestones, tasks, and
  updates; the API does not upload or serve the files itself.

## App design and scaffolding

Flux can carry a project from idea to generated code. The design lives in
these resources, all scoped to project members:

| Resource | Purpose |
|---|---|
| `entities` | A model of the app (`project`, `name`, `description`). |
| `fields` | Attributes of an entity. `type` is generic: `string`, `text`, `int`, `bigint`, `decimal`, `float`, `bool`, `date`, `datetime`, `time`, `uuid`, `json`, `email`, `url`. Also `nullable`, `unique`, `default`, `max_length`, `order`. |
| `relations` | `source` → `target` entity with `kind` (`fk`, `m2m`, `o2o`), `name`, `related_name`, `on_delete` (`cascade`, `protect`, `set_null`). Both ends must be in the same project. |
| `stack-profiles` | One per project: `targets` (`django`, `typescript`, `csharp`), `api_naming`, `auth_method`, `database`, `app_label`, `namespace`. |
| `resources` | An API resource per entity: `path`, `operations` (`list`, `retrieve`, `create`, `update`, `delete`), `filters`, `ordering`. |
| `roles`, `role-permissions` | A role and what it may do on a resource, with `scope` (`all`, `own`, `member`). |
| `screens` | `name`, `route`, the `entities` shown, and an optional `parent`. |
| `integrations` | External services and the `env_vars` they need. For an inbound data API also `base_url`, auth, timeout, retries, rate limit and cache time; see [Inbound API integrations](#inbound-api-integrations). |
| `integration-operations` | One call against an inbound data API, with parameters, paging, a real sample response and a mapping onto an entity. |
| `seed-rows` | Example data (`data` object) per entity. |

### Generating code

```text
GET  /api/flux/projects/{id}/scaffold/?target=django|typescript|csharp|skeleton|design|integration
POST /api/flux/projects/{id}/scaffold-document/   {"target": "django"}
POST /api/flux/projects/{id}/generate-tasks/
```

`scaffold` returns `{"target": ..., "files": [{"path": ..., "content": ...}]}`.
Nothing is written to disk. The generators are pure functions over a plain
dict (`flux/services/scaffold/`), so they can be tested without a database.

- `django`: an app package (`__init__.py`, `apps.py`, `models.py`), and when
  resources exist `serializers.py`, `views.py` (viewsets with exactly the
  chosen operations) and `urls.py`; with roles a `permissions.py` role matrix;
  with seed rows `fixtures/*.json`. Viewsets use `AllowAny` when the stack's
  `auth_method` is `none`.
- `typescript`: `types.ts`, plus `api.ts` (resources) and `routes.ts` (screens).
  The client sends the CSRF token for `session` auth and exports
  `setAuthToken` for `token`/`jwt` auth.
- `csharp`: `Models/*.cs`, `Data/AppDbContext.cs` (with relations and delete
  behaviour configured) and, when resources exist, `Controllers/*.cs`.
  `[Authorize]` is omitted when `auth_method` is `none`.
- `skeleton`: `README.md`, `.env.example` (including integration variables),
  `.gitignore`, `docker-compose.yml`, CI workflow and a `Dockerfile`, plus the
  base project: for Django `manage.py`, `config/settings.py`, `config/urls.py`
  (including login endpoints for `token`/`jwt`) and `requirements.txt`; for C#
  a `.csproj` and `Program.cs`. Django is used as the backend when both
  `django` and `csharp` are targets. `requests` (and `django-tasks` with its
  settings, when a sync is scheduled) are added when integrations need them.
- `integration`: for each inbound data API, a Django client, sync, tasks,
  management command, tests and a docs page; see
  [Inbound API integrations](#inbound-api-integrations).

`scaffold-document` stores the result as a markdown document named
`Scaffold: <target>` and updates it in place on later calls.
`generate-tasks` creates missing standard milestones and tasks (data model,
API, permissions, screens, tests) and never duplicates existing ones.

The generated role matrix reads the role from `request.user.role`. Enforcing
`own`/`member` scopes in `get_queryset` is left to the generated project.

### Inbound API integrations

An integration with a `base_url` and one or more `integration-operations`
describes an external data API the app reads from (the pattern behind the
Tempus sources such as Lantmäteriet and Trafikverket). The design is checked
against a **real sample response**, so a mapping can never point at a field the
API does not return or at a value of the wrong type.

Integration settings: `base_url` (https only), `auth_type` (`none`,
`api_key_header`, `api_key_query`, `bearer`, `basic`, `oauth_client`) with the
settings it needs (`auth_name`, `auth_env_var`, `auth_secret_env_var`,
`oauth_token_url`), `timeout_seconds` (1-120), `retries` (0-5),
`rate_limit_per_minute` and `cache_ttl_seconds`. Only the *names* of
environment variables are stored, never secrets; they are added to the
generated `.env.example`.

An operation has:

- `name` (a lowercase Python identifier), `method` (`GET` or `POST`), `path`
  (`{param}` marks path parameters) and `body_format` (`json` or `form`).
- `params`: `{name, in, type, required, default, description}` with `in` one of
  `query`, `path`, `body`, `header` and `type` one of `string`, `int`, `float`,
  `bool`. Path placeholders must match the path params exactly.
- `items_path`: dotted path to the list of records (empty if the response is the
  list; a single object counts as one record).
- `pagination`: `none`, `offset`, `page` or `cursor`, with `pagination_config`
  (offset: `limit_param`, `offset_param`, `page_size`; page: `page_param`,
  `page_size`, `first_page`, optional `size_param`; cursor: `cursor_param`,
  `next_cursor_path`, optional `size_param` and `page_size`; all: `max_pages`,
  default 100). A run that exceeds `max_pages` fails instead of crawling on.
- `filters`: `{path, op, value}` with `op` one of `eq`, `ne`, `in`, `not_null`,
  `is_null`, applied to each record (for example `meta.deleted eq false`).
- `entity`, `mappings` (`{path, field}` from a record to an entity field or to a
  fk/o2o relation, which stores the key), `key_field` (a plain field that
  identifies a record), `sync`, `sync_interval_minutes` and `cache_ttl_seconds`.
- `sample_response`: a real response captured from the live API (at most
  200 kB). It is required as soon as there are mappings.

Rules that answer `400`: the mapped paths and filter paths must exist in the
sample; mapped values must fit the field type (`null` only for nullable
fields); many-to-many relations cannot be mapped; `key_field` must be a mapped
plain field; `sync` needs an entity, mappings and a `key_field`;
`sync_interval_minutes` needs `sync`.

`scaffold?target=integration` returns, per integration with operations:

- `<app>/integrations/<name>.py`: the client, with one function per operation
  (`use_cache=False` bypasses the cache), configuration errors for missing
  environment variables, retries on `429` and `5xx` (honouring `Retry-After`),
  a rate limiter, OAuth token reuse, pagination, filters and a `map_<operation>`
  function.
- `<app>/integrations/<name>_sync.py` and `management/commands/sync_<name>.py`
  for operations with `sync`: upserts one record per item, keyed on
  `key_field`, and skips records with a missing key or a missing required field.
- `<app>/tasks.py` for operations with `sync_interval_minutes`: a `django_tasks`
  task that re-queues itself, like the other background jobs.
- `<app>/tests/test_<name>.py` with the sample responses as fixtures, and
  `docs/integrations/<name>.md`.

Only JSON responses are supported. For XML bodies, WKT geometry, OGC APIs or
unusual paging, use the generated client as a starting point and adapt it by
hand, as described in the Tempus guide for adding a data source.
`generate-tasks` adds one "verify against the live API" task per operation.

### Visual identity

An identity (`/identities/`) is a brand profile owned by one user and reusable
by many projects: colours with roles and light/dark values, typefaces and type
scale, spacing, radii and shadows, logo and icon assets, an accessibility
target (`AA` or `AAA`) and free-form guidelines.

Themes: `theme_modes` is `light`, `dark` or `both` (default). With `both`,
every colour needs a light **and** a dark value, `default_mode` (`system`,
`light` or `dark`) says which applies first, shadows can be overridden in
`shadows_dark`, and each logo/icon asset has a `mode` (`any`, `light`, `dark`).
Contrast is checked for each supported mode. In the generated CSS the app
switches theme with `data-theme="light|dark"` on `<html>`. Only the owner can change or
delete it; members of projects that use it can read it.

A project opts in with `include_identity` (default `false`) and picks one with
`identity`. Turning the switch off clears the identity, and only identities you
own can be chosen. Deleting an identity leaves the projects, with
`identity: null`.

For an opted-in project, `scaffold?target=design` returns `identity/fonts.css`,
`tokens.css`, `tailwind.theme.css` (Tailwind v4 `@theme`), `tailwind.theme.ts`,
`tokens.ts`, `assets.ts` and `STYLEGUIDE.md` (the style guide includes WCAG
contrast results for the colour roles). The `skeleton` target adds
`identity/STYLEGUIDE.md` and `generate-tasks` adds an `Identitet: <name>` task,
both only for opted-in projects. `design` answers `400` for other projects.

All values that end up in CSS are validated (hex colours, plain font names,
`https://` or root-relative URLs, no `;`, `{}` or `url(` in shadows).

Validation: relation names may not equal a field name on the same entity,
seed-row keys must be fields, relations or `id` of the entity, and role,
permission, screen-route and integration names must be unique per project
(the Codex import answers `400` instead of failing on the database).

## Codex plan API

`/api/flux/codex/` is a separate, token-only surface for private
Codex-managed projects. It does not grant access to the general Flux CRUD API.
Its token is supplied as `Authorization: Codex <token>` and can only access a
project owned solely by that token's user.

| Path | Method | Purpose |
|---|---|---|
| `codex/projects/` | GET | List the caller's private Codex projects. |
| `codex/projects/` | POST | Import a new project plan. |
| `codex/projects/{id}/` | GET | Read one private project plan. |
| `codex/projects/{id}/plan/` | POST | Append an approved plan. |
| `codex/projects/{id}/tasks/` | POST | Add a task. |
| `codex/projects/{id}/tasks/{task_id}/status/` | PATCH | Set a task's `status`. |
| `codex/projects/{id}/milestones/{milestone_id}/status/` | PATCH | Set a milestone's `status`. |
| `codex/projects/{id}/documents/{document_id}/` | PATCH | Partially update a document. |
| `codex/projects/{id}/scaffold/?target=` | GET | Generate code files from the project design. |
| `codex/identities/` | GET | List the visual identities the token's user owns. |

Plans (`POST codex/projects/` and `.../plan/`) also accept the design keys
`entities` (with nested `fields`), `relations`, `stack_profile`, `resources`,
`roles`, `screens`, `integrations` and `seeds`. Items link through `ref` values
(`source_ref`, `target_ref`, `entity_ref`, `resource_ref`, `entity_refs`,
`parent_ref`); `entity_ref` may also name an existing entity of the project.

An integration in a plan may carry `operations`; an operation names the entity
it maps onto with `entity_ref`, and a mapping is rejected unless the operation
has a `sample_response`.

A plan can also carry `include_identity` (boolean), `identity` (creates and
attaches a new shared identity) or `identity_id` (attaches one the token's user
already owns; list them with `GET codex/identities/`). Projects do not include
an identity unless asked.
