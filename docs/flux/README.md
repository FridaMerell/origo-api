# Flux documentation

Flux is the project-management API mounted at `/api/flux/`.

People are added to a project either directly or through a shareable invite
link — see [Inbjudningar](../accounts/invitations.md).

## API resources

- `projects`
- `milestones`
- `tasks`
- `updates`

All four resources are exposed through Django REST Framework viewsets and
support standard list, retrieve, create, update, and delete actions for
authenticated users scoped to projects they belong to.

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
