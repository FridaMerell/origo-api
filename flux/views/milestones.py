"""Milestone views."""
from rest_framework import permissions, viewsets

from flux.models import Milestone
from flux.serializers import MilestoneSerializer


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
