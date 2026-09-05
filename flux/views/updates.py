"""Update views."""
from rest_framework import permissions, viewsets

from flux.models import Update
from flux.serializers import UpdateSerializer


class UpdateViewSet(viewsets.ModelViewSet):
    serializer_class = UpdateSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['id', 'project', 'milestone', 'task']

    def get_queryset(self):
        queryset = Update.objects.filter(project__members=self.request.user)
        if self.action in ('update', 'partial_update'):
            return queryset.select_related('project', 'milestone', 'task')
        return queryset

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)
