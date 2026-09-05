"""Venture and venture-task views."""
from rest_framework import permissions, viewsets

from verso.models import Venture, VentureTask
from verso.serializers import VentureSerializer, VentureTaskSerializer


class VentureViewSet(viewsets.ModelViewSet):
    serializer_class = VentureSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['house']

    def get_queryset(self):
        return Venture.objects.filter(
            house__members=self.request.user,
        ).distinct()


class VentureTaskViewSet(viewsets.ModelViewSet):
    serializer_class = VentureTaskSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['venture', 'completed']

    def get_queryset(self):
        queryset = VentureTask.objects.filter(
            venture__house__members=self.request.user,
        ).distinct()
        house_id = self.request.query_params.get('venture__house')
        if self.action == 'list' and house_id:
            queryset = queryset.filter(venture__house_id=house_id)
        return queryset
