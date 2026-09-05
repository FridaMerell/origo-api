"""Update views."""
from django.db.models import Q
from rest_framework import permissions, viewsets

from verso.models import VersoUpdate
from verso.serializers import VersoUpdateSerializer


class UpdateViewSet(viewsets.ModelViewSet):
    serializer_class = VersoUpdateSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['venture', 'task', 'author']

    def get_queryset(self):
        queryset = VersoUpdate.objects.filter(
            Q(house__members=self.request.user)
            | Q(venture__house__members=self.request.user)
            | Q(task__venture__house__members=self.request.user)
        ).distinct().order_by('-created_at')
        house_id = self.request.query_params.get('house')
        if self.action == 'list' and house_id:
            queryset = queryset.filter(
                Q(house_id=house_id)
                | Q(venture__house_id=house_id)
                | Q(task__venture__house_id=house_id)
            )
        return queryset

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)
