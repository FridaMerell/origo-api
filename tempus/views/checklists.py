"""Checklist and observation views."""
import uuid
from urllib.parse import urlsplit, urlunsplit

from django.db.models import Exists, OuterRef, Subquery
from django_filters.rest_framework import CharFilter, FilterSet, UUIDFilter
from rest_framework import permissions, viewsets
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from origo.pagination import StandardPagination
from tempus.serializers import (
    ChecklistItemSerializer,
    ChecklistRegisterItemSerializer,
    ChecklistSerializer,
    ObservationSerializer,
)
from tempus.models import Checklist, ChecklistItem, Observation
from tempus.services import checklists


class ObservationFilter(FilterSet):
    """Filters for a user's observations."""

    checklist = UUIDFilter(field_name="checklist_items__checklist_id")
    # Accepts either a Species UUID (primary key) or a Dyntaxa taxon id.
    species = CharFilter(method="filter_species")

    class Meta:
        model = Observation
        fields = ["species", "checklist_items"]

    def filter_species(self, queryset, name, value):
        value = value.strip()
        if not value:
            return queryset
        try:
            uuid.UUID(value)
        except (ValueError, AttributeError):
            pass
        else:
            return queryset.filter(species_id=value)
        if value.isdigit():
            return queryset.filter(species__dyntaxa_taxon_id=int(value))
        raise ValidationError(
            {"species": "Ange ett Species-UUID eller ett Dyntaxa-taxon-id."}
        )


class ChecklistRegisterPagination(StandardPagination):
    max_page_size = 250

    @staticmethod
    def _relative_url(url):
        if url is None:
            return None
        parts = urlsplit(url)
        return urlunsplit(("", "", parts.path, parts.query, ""))

    def get_next_link(self):
        return self._relative_url(super().get_next_link())

    def get_previous_link(self):
        return self._relative_url(super().get_previous_link())


class ChecklistViewSet(viewsets.ModelViewSet):
    serializer_class = ChecklistSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ["start_date", "geo_area", "route"]

    def get_queryset(self):
        return Checklist.objects.filter(user=self.request.user).select_related("geo_area", "route")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(
        detail=True,
        methods=["get"],
        url_path="register",
        pagination_class=ChecklistRegisterPagination,
    )
    def register(self, request, pk=None):
        checklist = self.get_object()
        observations = Observation.objects.filter(
            user=request.user,
            checklist_items=OuterRef("pk"),
        ).order_by("-observed_at", "-created_at", "-pk")
        queryset = (
            ChecklistItem.objects.filter(checklist=checklist)
            .select_related("species")
            .annotate(
                is_observed=Exists(observations),
                latest_observation_id=Subquery(observations.values("pk")[:1]),
            )
        )
        page = self.paginate_queryset(queryset)
        serializer = ChecklistRegisterItemSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)


class ChecklistItemViewSet(viewsets.ModelViewSet):
    serializer_class = ChecklistItemSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ["checklist", "species"]

    def get_queryset(self):
        return ChecklistItem.objects.filter(checklist__user=self.request.user).select_related("checklist", "species")


class ObservationViewSet(viewsets.ModelViewSet):
    serializer_class = ObservationSerializer
    authentication_classes = [SessionAuthentication, TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    filterset_class = ObservationFilter

    def get_queryset(self):
        return (
            Observation.objects.filter(user=self.request.user)
            .prefetch_related("checklist_items")
            .distinct()
        )

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=False, methods=["post"], url_path="sync-checklists")
    def sync_checklists(self, request):
        observations_linked, checklist_item_links_created = (
            checklists.sync_observations_to_checklists(user=request.user)
        )
        return Response(
            {
                "observations_linked": observations_linked,
                "checklist_item_links_created": checklist_item_links_created,
            }
        )
