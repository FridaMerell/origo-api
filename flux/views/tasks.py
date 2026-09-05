"""Task views."""
from django.db.models import Count, Prefetch
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
        queryset = (
            Task.objects.filter(project__members=self.request.user)
            .annotate(update_count=Count('updates'))
        )
        if self.action in ('list', 'retrieve'):
            user_model = self.request.user.__class__
            return queryset.prefetch_related(
                Prefetch(
                    'subtasks',
                    queryset=Task.objects.only('id', 'parent_id'),
                ),
                Prefetch('requirements', queryset=Task.objects.only('id')),
                Prefetch('required_by', queryset=Task.objects.only('id')),
                Prefetch('assignees', queryset=user_model.objects.only('id')),
            )
        if self.action in ('update', 'partial_update'):
            return queryset.select_related('project', 'milestone', 'parent')
        return queryset

    def perform_create(self, serializer):
        task = serializer.save()
        task.update_count = 0
