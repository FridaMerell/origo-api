"""Document views."""
from rest_framework import permissions, viewsets

from flux.models import Document
from flux.serializers import DocumentSerializer


class DocumentViewSet(viewsets.ModelViewSet):
    serializer_class = DocumentSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['id', 'project', 'milestone', 'task', 'kind']

    def get_queryset(self):
        queryset = Document.objects.filter(project__members=self.request.user)
        if self.action in ('update', 'partial_update'):
            return queryset.select_related('project', 'milestone', 'task')
        return queryset

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)
