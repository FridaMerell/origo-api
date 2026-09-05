"""Read-mostly reference-data views: phenophases, sources, and geo areas."""
from tempus.api.common import SharedDataViewSet
from tempus.models import GeoArea, Phenophase, Source
from tempus.serializers import GeoAreaSerializer, PhenophaseSerializer, SourceSerializer


class PhenophaseViewSet(SharedDataViewSet):
    queryset = Phenophase.objects.all()
    serializer_class = PhenophaseSerializer
    filterset_fields = ["code"]


class SourceViewSet(SharedDataViewSet):
    queryset = Source.objects.all()
    serializer_class = SourceSerializer


class GeoAreaViewSet(SharedDataViewSet):
    queryset = GeoArea.objects.all()
    serializer_class = GeoAreaSerializer
    filterset_fields = ["kind", "country_code"]

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        response["Cache-Control"] = "private, max-age=3600"
        return response
