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
    list_private_project_plans_for_user,
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
