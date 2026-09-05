"""Milestone views."""
from django.db.models import Count, Prefetch
from rest_framework import permissions, viewsets

from flux.models import Milestone, Tag
from flux.serializers import MilestoneSerializer


class MilestoneViewSet(viewsets.ModelViewSet):
    serializer_class = MilestoneSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['id', 'project', 'status']

    def get_queryset(self):
        queryset = (
            Milestone.objects.filter(project__members=self.request.user)
            .annotate(update_count=Count('updates'))
        )
        if self.action in ('list', 'retrieve'):
            return queryset.prefetch_related(
                Prefetch('tags', queryset=Tag.objects.only('id'))
            )
        if self.action in ('update', 'partial_update'):
            return queryset.select_related('project')
        return queryset

    def perform_create(self, serializer):
        milestone = serializer.save()
        milestone.update_count = 0
