"""Income views."""
from rest_framework import permissions, viewsets

from verso.models import Income
from verso.serializers import IncomeSerializer


class IncomeViewSet(viewsets.ModelViewSet):
    serializer_class = IncomeSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['house', 'booking']

    def get_queryset(self):
        return Income.objects.filter(
            house__members=self.request.user
        ).distinct().order_by('-date_received')

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
