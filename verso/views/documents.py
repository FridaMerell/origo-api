"""Document views."""
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, permissions, viewsets

from verso.models import Document
from verso.serializers import DocumentSerializer


class DocumentViewSet(viewsets.ModelViewSet):
    serializer_class = DocumentSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['house', 'venture', 'tags', 'people', 'content_type']
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    ordering_fields = ['document_date', 'created_at', 'title']

    def get_queryset(self):
        return Document.objects.filter(
            house__members=self.request.user,
        ).prefetch_related('tags', 'people').distinct()
