"""Visual identity views."""
from django.db.models import Q
from rest_framework import permissions, viewsets

from flux.models import VisualProfile
from flux.serializers import VisualProfileSerializer


class VisualProfileViewSet(viewsets.ModelViewSet):
    """Identities are owned by one user and can be reused by many projects.

    Anyone can read an identity they own or that one of their projects uses;
    only the owner may change or delete it.
    """

    serializer_class = VisualProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['id', 'name']

    def get_queryset(self):
        user = self.request.user
        if self.action in ('update', 'partial_update', 'destroy'):
            return VisualProfile.objects.filter(owner=user)
        return VisualProfile.objects.filter(Q(owner=user) | Q(projects__members=user)).distinct()

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)
