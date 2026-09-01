from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters

from origo.pagination import StandardPagination
from tempus.api.common import SharedDataViewSet
from tempus.api.category_serializers import (
    SpeciesCategoryListSerializer,
    SpeciesCategorySerializer,
)
from tempus.models import SpeciesCategory


class SpeciesCategoryViewSet(SharedDataViewSet):
    queryset = SpeciesCategory.objects.all()
    serializer_class = SpeciesCategorySerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["taxon_id", "parent_category", "is_primary"]
    ordering_fields = [
        "taxon_id",
        "label",
        "parent_category",
        "parent_category__label",
        "is_primary",
    ]
    ordering = ["taxon_id", "label"]
    lookup_field = "taxon_id"

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == "retrieve":
            return queryset.prefetch_related("taxon", "memberships", "children")
        return queryset

    def get_serializer_class(self):
        if self.action == "list":
            return SpeciesCategoryListSerializer
        return super().get_serializer_class()
