"""Token-only API for private Codex-managed Flux projects."""
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.authentication import CodexTokenAuthentication
from flux.codex_plans import (
    CodexPlanError,
    add_task_to_private_project,
    append_plan_to_private_project,
    get_private_project_plan_for_user,
    import_project_plan_for_user,
    list_identities_for_user,
    list_private_project_plans_for_user,
    scaffold_private_project,
    update_document_in_private_project,
    update_milestone_status_in_private_project,
    update_task_status_in_private_project,
)


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
            project = import_project_plan_for_user(request.user, request.data)
        except CodexPlanError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(project, status=status.HTTP_201_CREATED)


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
            task = add_task_to_private_project(request.user, project_id, request.data)
        except CodexPlanError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(task, status=status.HTTP_201_CREATED)


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
            project = append_plan_to_private_project(request.user, project_id, request.data)
        except CodexPlanError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(project, status=status.HTTP_201_CREATED)
