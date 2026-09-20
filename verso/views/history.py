"""Person, history event and interview views."""
from rest_framework import permissions, viewsets

from verso.models import HistoryEvent, Person, PersonRelation
from verso.serializers import HistoryEventSerializer, PersonRelationSerializer, PersonSerializer


class PersonViewSet(viewsets.ModelViewSet):
    serializer_class = PersonSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['house']

    def get_queryset(self):
        return Person.objects.filter(house__members=self.request.user).select_related('portrait').distinct()


class PersonRelationViewSet(viewsets.ModelViewSet):
    serializer_class = PersonRelationSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['house', 'person', 'related', 'kind']

    def get_queryset(self):
        return PersonRelation.objects.filter(house__members=self.request.user).distinct()


class HistoryEventViewSet(viewsets.ModelViewSet):
    serializer_class = HistoryEventSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['house', 'people', 'photos', 'date_precision']

    def get_queryset(self):
        return HistoryEvent.objects.filter(
            house__members=self.request.user,
        ).prefetch_related('people', 'photos').distinct()
