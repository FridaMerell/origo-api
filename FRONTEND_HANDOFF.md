# Frontend handoff: normalized API contracts

## Purpose

The frontend should load one complete, ID-preserving design definition and
derive all relationships locally. It must not infer API response shapes from
entities or make supplemental design requests.

## Single design request

Load:

`GET /api/flux/projects/<project_id>/design/`

The response contains:

- `entities`, `fields`, `relations`, `stack_profile`
- `resources`, `api_operations`, `api_projections`, `api_operation_responses`
- `providers`, `roles`, `role_permissions`, `screens`
- `integrations`, `integration_operations`, `seed_rows`

Keep all returned numeric IDs unchanged. Build client-side lookup maps by ID
for each collection.

## Contract model

`Resource` is the API surface for one Entity.

`ApiOperation` is the only endpoint definition. Use its `title`,
`description`, `method`, `path`, `parameters`, `request_schema`, and
`pagination` to describe and render an operation.

`ApiOperationResponse` declares every documented status code for an operation.
Its nullable `projection` points to an `ApiProjection` when the response has a
body. A null projection means bodyless response.

`ApiProjection.schema` is a reusable response schema. Do not automatically use
an Entity as an API response type: an operation may return an ID-only,
reference, summary, detail, or custom shape.

## Required ID joins

| Source | Join | Meaning |
| --- | --- | --- |
| Resource | `entity` | Domain entity behind the API resource |
| ApiOperation | `resource` | API surface that owns the endpoint |
| ApiOperationResponse | `operation`, `projection` | Endpoint result and optional response body schema |
| Provider | `resources` | Frontend data boundary; derive entities through the resources |
| RolePermission | `api_operation` | Permissioned endpoint plus its scope |
| Screen | `parent`, `entities` | Navigation hierarchy and relevant entities |
| IntegrationOperation | `integration`, `entity` | External workflow; separate from internal API operations |

## Implementation sequence

1. Define TypeScript types for the aggregate and all ID relationships.
2. Fetch the aggregate once per selected project and index every collection by
   ID.
3. Build provider state from `provider.resources`; never use a parallel entity
   selection.
4. Render API documentation and request forms from `ApiOperation`.
5. Render every declared response status from `ApiOperationResponse`; resolve
   `projection` through `ApiProjection` before rendering a body.
6. Use `RolePermission.api_operation` and `scope` for operation-level access.
7. Build navigation from `Screen.parent` and screen/entity associations.
8. Keep `IntegrationOperation` flows separate from internal `ApiOperation`
   controls.

## Acceptance criteria

- Exactly one request retrieves the complete design definition.
- Every cross-reference is resolved via a preserved ID.
- Request UI is driven by parameters and request schema, not guessed fields.
- Bodyless responses and multiple status codes render correctly.
- Reused projections work across multiple operations.
- Custom operations are supported alongside list/retrieve/create/update/delete.
- A provider with several resources exposes the corresponding entity scope by
  derivation only.
- No extra API request is made merely to derive a design summary.
