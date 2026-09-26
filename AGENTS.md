# Flux Codex integration

## Local Flux exception

Codex may call the dedicated local Flux Codex API at
`http://origo.test:8000/api/flux/codex` for this repository. This exception
applies only to that API and only with `FLUX_CODEX_TOKEN`; it does not permit
starting, managing, or calling other local development servers, databases, or
migration commands.

## Recurring background tasks

When adding a new self-scheduling periodic task, register it in
`accounts/management/commands/ensure_scheduled_tasks.py` in the same change.
Include the correct initial `run_after` value when the task should not run
immediately. The command must remain idempotent: it must not enqueue a new
chain when a `READY` or `RUNNING` task with the same task path already exists.
Event-driven tasks that are enqueued by a request or signal do not need to be
registered there.

Flux is a live service.  When a user asks Codex to create or upload a Flux
plan, Codex may upload it directly without an additional confirmation, using
only the dedicated Codex API described here.

## Flux is the source of truth for project design

Keep the corresponding private Flux project current for every implementation
change. This applies in every chat working in this repository, without the
user needing to repeat the request. Update the actual Flux design entities,
fields, relations, resources, roles, screens, and documents that are affected;
updating only a narrative document is not sufficient. Before reporting a
change as complete, read the Flux project back and verify that every affected
design artifact reflects the implemented state. If the dedicated Codex API
lacks a safe update operation, implement that operation in the Flux Codex API
as part of the change and clearly report that a deployment is required before
the live project can be synchronized. Never create duplicate design entities
as a substitute for updating an existing one.

- The live API base URL is supplied through `FLUX_CODEX_API_BASE_URL` and must
  end in `/api/flux/codex`.
- The user token is supplied only through `FLUX_CODEX_TOKEN`.  Send it as
  `Authorization: Codex <token>`.  Never print it, save it to a file, or use it
  with any other endpoint.
- Upload a plan with `POST {base}/projects/`.
- List the current user's private Codex projects with `GET {base}/projects/`.
- Read one of those projects with `GET {base}/projects/{id}/`.
- Do not call the generic `/api/flux/projects/`, `/milestones/`, `/tasks/`, or
  `/updates/` endpoints through this integration.  Do not alter membership,
  delete resources, or use a project owned by another user.

### API contracts

`Resource` is the API surface for one Entity and stores only its path, title,
and description. `ApiOperation` is the only endpoint contract: it owns key,
method, path, title, description, parameters, request schema, pagination and
one or more `ApiOperationResponse` status declarations. A response optionally
references an `ApiProjection`, which is a reusable project-level response
schema (`name`, `description`, `schema`) rather than an endpoint.

Read `api_operations`, `api_operation_responses`, and `api_projections` from
`GET {base}/projects/{id}/`. Use persistent IDs and read the project back after
each write. RolePermission references an ApiOperation and keeps its scope.

### Providers

`Provider` defines a generated frontend data boundary by selecting one or more
resources belonging to the same project. Entity scope is derived from each
resource; do not send or maintain `entity_ids`.

For a private project, agents may manage providers through:

- `POST {base}/projects/{project_id}/providers/`
- `PATCH {base}/projects/{project_id}/providers/{provider_id}/`
- `DELETE {base}/projects/{project_id}/providers/{provider_id}/`

Create payloads require `name` and `resource_ids`. Patch only the fields that
change; omitted selections are preserved. All IDs must be persistent IDs from
the project read response and belong to that project. Read the project back
after every provider write.

The upload payload follows Flux's domain model directly:

```json
{
  "name": "Project name",
  "description": "Optional project description",
  "milestones": [
    {"ref": "design", "title": "Design", "description": "", "status": "not_started", "target_date": "2026-09-30"}
  ],
  "tasks": [
    {"ref": "wireframes", "title": "Create wireframes", "milestone_ref": "design", "parent_ref": null, "priority": "medium", "status": "not_started", "due_date": null}
  ],
  "updates": [
    {"content": "Initial plan created.", "milestone_ref": "design", "task_ref": null}
  ]
}
```

`ref`, `milestone_ref`, `parent_ref`, and `task_ref` exist only inside the
upload payload.  Flux returns persistent numeric IDs after creation.
