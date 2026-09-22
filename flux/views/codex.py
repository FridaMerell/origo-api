"""Token-only API for private Codex-managed Flux projects."""
import hashlib
import json
import re

from django.db import IntegrityError, transaction
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.authentication import CodexTokenAuthentication
from flux.models import CodexIdempotencyRequest
from flux.codex_plans import (
    CodexPlanError,
    add_task_to_private_project,
    append_plan_to_private_project,
    delete_entity_field_in_private_project,
    upsert_relations_to_private_project,
    get_private_project_plan_for_user,
    import_project_plan_for_user,
    list_identities_for_user,
    list_private_project_plans_for_user,
    scaffold_private_project,
    upsert_entity_field_in_private_project,
    update_entity_in_private_project,
    update_resource_in_private_project,
    update_role_in_private_project,
    update_document_in_private_project,
    update_milestone_status_in_private_project,
    update_task_status_in_private_project,
)


IDEMPOTENCY_KEY_PATTERN = re.compile(r'^[A-Za-z0-9._:-]{16,128}$')


class CodexIdempotencyConflict(CodexPlanError):
    """A retry key was reused with a different write payload."""


def _response_is_summary(request):
    response_mode = request.query_params.get('response')
    if response_mode in (None, 'representation'):
        return False
    if response_mode == 'summary':
        return True
    raise CodexPlanError('response must be either summary or representation.')


def _created_counts(payload):
    fields = (
        'milestones', 'tasks', 'documents', 'updates', 'entities', 'relations',
        'resources', 'roles', 'screens', 'integrations', 'seeds',
    )
    return {
        field: len(payload.get(field, []))
        for field in fields
        if isinstance(payload.get(field, []), list) and payload.get(field, [])
    }


def _project_write_summary(project, payload):
    return {
        'id': project.id,
        'project_id': project.id,
        'name': project.name,
        'created': _created_counts(payload),
    }


def _task_write_summary(task):
    return {
        'id': task.id,
        'project_id': task.project_id,
        'title': task.title,
        'created': {'tasks': 1},
    }


def _request_hash(payload):
    try:
        encoded = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
    except (TypeError, ValueError) as exc:
        raise CodexPlanError('request body must be JSON.') from exc
    return hashlib.sha256(encoded).hexdigest()


def _idempotent_write(request, write):
    """Execute one write once per token/key and retain its successful response."""
    key = request.headers.get('Idempotency-Key')
    if key is None:
        return (*write(), False)
    if not IDEMPOTENCY_KEY_PATTERN.fullmatch(key):
        raise CodexPlanError('Idempotency-Key must contain 16 to 128 safe characters.')

    payload_hash = _request_hash(request.data)
    with transaction.atomic():
        try:
            record = CodexIdempotencyRequest.objects.select_for_update().get(
                token=request.auth,
                key=key,
            )
            created = False
        except CodexIdempotencyRequest.DoesNotExist:
            try:
                with transaction.atomic():
                    record = CodexIdempotencyRequest.objects.create(
                        token=request.auth,
                        key=key,
                        request_hash=payload_hash,
                        response_status=status.HTTP_201_CREATED,
                        response_data={},
                    )
                created = True
            except IntegrityError:
                record = CodexIdempotencyRequest.objects.select_for_update().get(
                    token=request.auth,
                    key=key,
                )
                created = False

        if not created:
            if record.request_hash != payload_hash:
                raise CodexIdempotencyConflict(
                    'Idempotency-Key was already used with a different request body.'
                )
            return record.response_data, record.response_status, True

        response_data, response_status = write()
        record.response_status = response_status
        record.response_data = response_data
        record.save(update_fields=['response_status', 'response_data'])
        return response_data, response_status, False


def _write_response(request, write):
    data, response_status, replayed = _idempotent_write(request, write)
    response = Response(data, status=response_status)
    if replayed:
        response['Idempotent-Replay'] = 'true'
    return response


class CodexProjectPlanListView(APIView):
    """Token-only API for private Codex-managed Flux projects.

    This deliberately does not expose the generic project CRUD API.  A token
    can only create a project where it becomes the sole member, and can only
    list similarly private projects owned by its user.
    """

    authentication_classes = [CodexTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(list_private_project_plans_for_user(request.user))

    def post(self, request):
        try:
            summary = _response_is_summary(request)

            def write():
                project = import_project_plan_for_user(
                    request.user,
                    request.data,
                    return_project=summary,
                )
                data = _project_write_summary(project, request.data) if summary else project
                return data, status.HTTP_201_CREATED

            return _write_response(request, write)
        except CodexIdempotencyConflict as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)
        except CodexPlanError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class CodexProjectPlanDetailView(APIView):
    """Read one private Codex-managed Flux project through a user token."""

    authentication_classes = [CodexTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, project_id):
        try:
            project = get_private_project_plan_for_user(request.user, project_id)
        except CodexPlanError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_404_NOT_FOUND)
        return Response(project)


class CodexIdentityListView(APIView):
    """List the visual identities the token's user owns."""

    authentication_classes = [CodexTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(list_identities_for_user(request.user))


class CodexProjectScaffoldView(APIView):
    """Return generated code files (django, typescript, csharp, skeleton) for a private project."""

    authentication_classes = [CodexTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, project_id):
        try:
            result = scaffold_private_project(request.user, project_id, request.query_params.get('target', ''))
        except CodexPlanError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result)


class CodexProjectTaskCreateView(APIView):
    """Create a task under an existing private Codex project."""

    authentication_classes = [CodexTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, project_id):
        try:
            summary = _response_is_summary(request)

            def write():
                task = add_task_to_private_project(
                    request.user,
                    project_id,
                    request.data,
                    return_task=summary,
                )
                data = _task_write_summary(task) if summary else task
                return data, status.HTTP_201_CREATED

            return _write_response(request, write)
        except CodexIdempotencyConflict as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)
        except CodexPlanError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class CodexProjectTaskStatusView(APIView):
    """Set the status of one task in a private Codex project."""

    authentication_classes = [CodexTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, project_id, task_id):
        try:
            task = update_task_status_in_private_project(request.user, project_id, task_id, request.data)
        except CodexPlanError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(task)


class CodexProjectMilestoneStatusView(APIView):
    """Set the status of one milestone in a private Codex project."""

    authentication_classes = [CodexTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, project_id, milestone_id):
        try:
            milestone = update_milestone_status_in_private_project(
                request.user, project_id, milestone_id, request.data
            )
        except CodexPlanError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(milestone)


class CodexProjectDocumentUpdateView(APIView):
    """Partially update one document in place within an existing private Codex project."""

    authentication_classes = [CodexTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, project_id, document_id):
        try:
            document = update_document_in_private_project(
                request.user, project_id, document_id, request.data
            )
        except CodexPlanError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(document)


class CodexProjectPlanAppendView(APIView):
    """Add a complete approved plan to an existing private Codex project."""

    authentication_classes = [CodexTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, project_id):
        try:
            summary = _response_is_summary(request)

            def write():
                project = append_plan_to_private_project(
                    request.user,
                    project_id,
                    request.data,
                    return_project=summary,
                )
                data = _project_write_summary(project, request.data) if summary else project
                return data, status.HTTP_201_CREATED

            return _write_response(request, write)
        except CodexIdempotencyConflict as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)
        except CodexPlanError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class CodexProjectEntityUpdateView(APIView):
    """Partially update one entity in a private Codex project."""

    authentication_classes = [CodexTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, project_id, entity_id):
        try:
            entity = update_entity_in_private_project(
                request.user, project_id, entity_id, request.data
            )
        except CodexPlanError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(entity)


class CodexProjectEntityFieldUpsertView(APIView):
    """Create or update one field on an entity in a private Codex project."""

    authentication_classes = [CodexTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, project_id, entity_id):
        try:
            field = upsert_entity_field_in_private_project(
                request.user, project_id, entity_id, request.data
            )
        except CodexPlanError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(field, status=status.HTTP_201_CREATED)

    def delete(self, request, project_id, entity_id, field_id):
        try:
            result = delete_entity_field_in_private_project(
                request.user, project_id, entity_id, field_id
            )
        except CodexPlanError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result, status=status.HTTP_204_NO_CONTENT)


class CodexProjectResourceUpdateView(APIView):
    """Partially update one entity's API resource in a private Codex project."""

    authentication_classes = [CodexTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, project_id, entity_id):
        try:
            resource = update_resource_in_private_project(
                request.user, project_id, entity_id, request.data
            )
        except CodexPlanError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(resource)


class CodexProjectRoleUpdateView(APIView):
    """Partially update one role in a private Codex project."""

    authentication_classes = [CodexTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, project_id, role_id):
        try:
            role = update_role_in_private_project(
                request.user, project_id, role_id, request.data
            )
        except CodexPlanError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(role)


class CodexProjectRelationsView(APIView):
    """Create, update, or remove relations on existing project entities."""

    authentication_classes = [CodexTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, project_id):
        try:
            project = upsert_relations_to_private_project(request.user, project_id, request.data)
        except CodexPlanError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(project, status=status.HTTP_200_OK)
