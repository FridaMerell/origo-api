from rest_framework import permissions, viewsets

from flux.models import Milestone, Project, Task, Update
from flux.serializers import MilestoneSerializer, ProjectSerializer, TaskSerializer, UpdateSerializer


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
