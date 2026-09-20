"""Entity, field and relation views."""
from rest_framework import permissions, viewsets

from flux.models import Entity, Field, Relation
from flux.serializers import EntitySerializer, FieldSerializer, RelationSerializer


class EntityViewSet(viewsets.ModelViewSet):
    serializer_class = EntitySerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['id', 'project']

    def get_queryset(self):
        return Entity.objects.filter(project__members=self.request.user)


class FieldViewSet(viewsets.ModelViewSet):
    serializer_class = FieldSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['id', 'entity', 'entity__project']

    def get_queryset(self):
        return Field.objects.filter(entity__project__members=self.request.user)


class RelationViewSet(viewsets.ModelViewSet):
    serializer_class = RelationSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['id', 'source', 'target', 'source__project']

    def get_queryset(self):
        return Relation.objects.filter(source__project__members=self.request.user)
