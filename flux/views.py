from rest_framework import permissions, viewsets

from flux.models import Project, Task
from flux.serializers import ProjectSerializer, TaskSerializer


class ProjectViewSet(viewsets.ModelViewSet):
    serializer_class = ProjectSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['members']

    def get_queryset(self):
        return Project.objects.filter(members=self.request.user).distinct()

    def perform_create(self, serializer):
        project = serializer.save()
        project.members.add(self.request.user)


class TaskViewSet(viewsets.ModelViewSet):
    serializer_class = TaskSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['project', 'parent', 'assignees', 'priority']

    def get_queryset(self):
        return Task.objects.filter(project__members=self.request.user).distinct()
