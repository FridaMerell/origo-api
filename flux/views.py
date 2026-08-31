from rest_framework import permissions, status, viewsets
from django.db import models
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.authentication import CodexTokenAuthentication
from flux.codex_plans import (
    CodexPlanError,
    add_task_to_private_project,
    get_private_project_plan_for_user,
    import_project_plan_for_user,
    list_private_project_plans_for_user,
)
from flux.models import Document, Milestone, Project, Tag, Task, Update
from flux.serializers import (
    DocumentSerializer,
    MilestoneSerializer,
    ProjectSerializer,
    TagSerializer,
    TaskSerializer,
    UpdateSerializer,
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


class ProjectViewSet(viewsets.ModelViewSet):
    serializer_class = ProjectSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['id', 'members']

    def get_queryset(self):
        return (
            Project.objects.filter(members=self.request.user)
            .distinct()
            .prefetch_related('members', 'milestones', 'tasks', 'updates')
        )

    def perform_create(self, serializer):
        project = serializer.save()
        project.members.add(self.request.user)


class MilestoneViewSet(viewsets.ModelViewSet):
    serializer_class = MilestoneSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['id', 'project', 'status']

    def get_queryset(self):
        return (
            Milestone.objects.filter(project__members=self.request.user)
            .distinct()
            .select_related('project')
            .prefetch_related('updates')
        )


class TagViewSet(viewsets.ModelViewSet):
    serializer_class = TagSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['id', 'name']

    def get_queryset(self):
        queryset = (
            Tag.objects.filter(
                models.Q(created_by=self.request.user)
                | models.Q(projects__members=self.request.user)
                | models.Q(milestones__project__members=self.request.user)
            )
            .distinct()
            .select_related('created_by')
        )
        if self.action in ('retrieve', 'update', 'partial_update', 'destroy'):
            return queryset.filter(created_by=self.request.user)
        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class DocumentViewSet(viewsets.ModelViewSet):
    serializer_class = DocumentSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['id', 'project', 'milestone', 'task', 'kind']

    def get_queryset(self):
        return (
            Document.objects.filter(project__members=self.request.user)
            .distinct()
            .select_related('project', 'milestone', 'task', 'author')
        )

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)


class TaskViewSet(viewsets.ModelViewSet):
    serializer_class = TaskSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = [
        'id',
        'project',
        'milestone',
        'parent',
        'assignees',
        'priority',
        'recurrence',
        'recurrence_source',
    ]

    def get_queryset(self):
        return (
            Task.objects.filter(project__members=self.request.user)
            .distinct()
            .select_related('project', 'milestone', 'parent', 'recurrence_source')
            .prefetch_related(
                'subtasks',
                'requirements',
                'required_by',
                'assignees',
                'updates',
            )
        )


class UpdateViewSet(viewsets.ModelViewSet):
    serializer_class = UpdateSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['id', 'project', 'milestone', 'task']

    def get_queryset(self):
        return (
            Update.objects.filter(project__members=self.request.user)
            .distinct()
            .select_related('project', 'milestone', 'task', 'author')
        )

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)
