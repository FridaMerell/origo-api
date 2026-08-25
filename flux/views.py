from rest_framework import permissions, viewsets

from flux.models import Milestone, Project, Task, Update
from flux.serializers import MilestoneSerializer, ProjectSerializer, TaskSerializer, UpdateSerializer


class ProjectViewSet(viewsets.ModelViewSet):
    serializer_class = ProjectSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['members']

    def get_queryset(self):
        return Project.objects.filter(members=self.request.user).distinct()

    def perform_create(self, serializer):
        project = serializer.save()
        project.members.add(self.request.user)


class MilestoneViewSet(viewsets.ModelViewSet):
    serializer_class = MilestoneSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['project', 'status']

    def get_queryset(self):
        return Milestone.objects.filter(project__members=self.request.user).distinct()


class TaskViewSet(viewsets.ModelViewSet):
    serializer_class = TaskSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['project', 'milestone', 'parent', 'assignees', 'priority']

    def get_queryset(self):
        return Task.objects.filter(project__members=self.request.user).distinct()


class UpdateViewSet(viewsets.ModelViewSet):
    serializer_class = UpdateSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['project', 'milestone', 'task']

    def get_queryset(self):
        return Update.objects.filter(project__members=self.request.user).distinct()

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)
