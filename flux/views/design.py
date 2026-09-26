"""Views for stack, resources, roles, screens, integrations and seed data."""
from rest_framework import permissions, viewsets

from flux.models import ApiOperation, ApiOperationResponse, ApiProjection, Integration, IntegrationOperation, Provider, Resource, Role, RolePermission, Screen, SeedRow, StackProfile
from flux.serializers import (
    ApiProjectionSerializer,
    ApiOperationResponseSerializer,
    ApiOperationSerializer,
    IntegrationOperationSerializer,
    IntegrationSerializer,
    ProviderSerializer,
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


class ApiProjectionViewSet(_MemberScopedViewSet):
    serializer_class = ApiProjectionSerializer
    queryset_model = ApiProjection
    member_lookup = 'project__members'
    filterset_fields = ['id', 'project']


class ApiOperationViewSet(_MemberScopedViewSet):
    serializer_class = ApiOperationSerializer
    queryset_model = ApiOperation
    member_lookup = 'resource__entity__project__members'
    filterset_fields = ['id', 'resource', 'resource__entity__project', 'key', 'method']


class ApiOperationResponseViewSet(_MemberScopedViewSet):
    serializer_class = ApiOperationResponseSerializer
    queryset_model = ApiOperationResponse
    member_lookup = 'operation__resource__entity__project__members'
    filterset_fields = ['id', 'operation', 'projection', 'status_code']


class ProviderViewSet(_MemberScopedViewSet):
    serializer_class = ProviderSerializer
    queryset_model = Provider
    filterset_fields = ['id', 'project', 'resources']


class RoleViewSet(_MemberScopedViewSet):
    serializer_class = RoleSerializer
    queryset_model = Role
    filterset_fields = ['id', 'project']


class RolePermissionViewSet(_MemberScopedViewSet):
    serializer_class = RolePermissionSerializer
    queryset_model = RolePermission
    member_lookup = 'role__project__members'
    filterset_fields = ['id', 'role', 'api_operation', 'role__project']


class ScreenViewSet(_MemberScopedViewSet):
    serializer_class = ScreenSerializer
    queryset_model = Screen
    filterset_fields = ['id', 'project', 'parent']


class IntegrationViewSet(_MemberScopedViewSet):
    serializer_class = IntegrationSerializer
    queryset_model = Integration
    filterset_fields = ['id', 'project', 'kind']


class IntegrationOperationViewSet(_MemberScopedViewSet):
    serializer_class = IntegrationOperationSerializer
    queryset_model = IntegrationOperation
    member_lookup = 'integration__project__members'
    filterset_fields = ['id', 'integration', 'integration__project', 'entity']


class SeedRowViewSet(_MemberScopedViewSet):
    serializer_class = SeedRowSerializer
    queryset_model = SeedRow
    member_lookup = 'entity__project__members'
    filterset_fields = ['id', 'entity', 'entity__project']
