"""Task views."""
from rest_framework import permissions, viewsets

from flux.models import Task
from flux.serializers import TaskSerializer


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
