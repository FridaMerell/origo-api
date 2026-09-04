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
- `kind` (`markdown`, `flowchart`, or `database_schema`)

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
