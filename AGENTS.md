# Flux Codex integration

Flux is a live service.  When a user asks Codex to create or upload a Flux
plan, Codex may upload it directly without an additional confirmation, using
only the dedicated Codex API described here.

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
