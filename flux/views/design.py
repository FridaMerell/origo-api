"""Views for stack, resources, roles, screens, integrations and seed data."""
from rest_framework import permissions, viewsets

from flux.models import Integration, Resource, Role, RolePermission, Screen, SeedRow, StackProfile
from flux.serializers import (
    IntegrationSerializer,
    ResourceSerializer,
    RolePermissionSerializer,
    RoleSerializer,
    ScreenSerializer,
    SeedRowSerializer,
    StackProfileSerializer,
)


class _MemberScopedViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    member_lookup = 'project__members'

    def get_queryset(self):
        return self.queryset_model.objects.filter(**{self.member_lookup: self.request.user}).distinct()


class StackProfileViewSet(_MemberScopedViewSet):
    serializer_class = StackProfileSerializer
    queryset_model = StackProfile
    filterset_fields = ['id', 'project']


class ResourceViewSet(_MemberScopedViewSet):
    serializer_class = ResourceSerializer
    queryset_model = Resource
    member_lookup = 'entity__project__members'
    filterset_fields = ['id', 'entity', 'entity__project']


class RoleViewSet(_MemberScopedViewSet):
    serializer_class = RoleSerializer
    queryset_model = Role
    filterset_fields = ['id', 'project']


class RolePermissionViewSet(_MemberScopedViewSet):
    serializer_class = RolePermissionSerializer
    queryset_model = RolePermission
    member_lookup = 'role__project__members'
    filterset_fields = ['id', 'role', 'resource', 'role__project']


class ScreenViewSet(_MemberScopedViewSet):
    serializer_class = ScreenSerializer
    queryset_model = Screen
    filterset_fields = ['id', 'project', 'parent']


class IntegrationViewSet(_MemberScopedViewSet):
    serializer_class = IntegrationSerializer
    queryset_model = Integration
    filterset_fields = ['id', 'project', 'kind']


class SeedRowViewSet(_MemberScopedViewSet):
    serializer_class = SeedRowSerializer
    queryset_model = SeedRow
    member_lookup = 'entity__project__members'
    filterset_fields = ['id', 'entity', 'entity__project']
