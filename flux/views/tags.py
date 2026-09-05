"""Tag views."""
from django.db import models
from rest_framework import permissions, viewsets

from flux.models import Tag
from flux.serializers import TagSerializer


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
