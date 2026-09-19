"""Checklist and observation views."""
import uuid
from urllib.parse import urlsplit, urlunsplit

from django.db.models import Count, Exists, OuterRef, Prefetch, Subquery
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
from tempus.models import (
    Checklist,
    ChecklistItem,
    Locale,
    Observation,
    SpeciesCategory,
    SpeciesCategoryMembership,
)
from tempus.services import checklists
from tempus.services.geo import point_in_multipolygon, point_in_polygon


class ObservationFilter(FilterSet):
    """Filters for a user's observations."""

    checklist = UUIDFilter(field_name="checklist_items__checklist_id")
    # Accepts either a Species UUID (primary key) or a Dyntaxa taxon id.
    species = CharFilter(method="filter_species")

    class Meta:
        model = Observation
        fields = ["species", "checklist_items", "locale"]

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
    pagination_class = StandardPagination
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ["start_date", "geo_area", "route", "locale"]

    def get_queryset(self):
        return Checklist.objects.filter(user=self.request.user).select_related(
            "geo_area", "route", "locale"
        )

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=True, methods=["post"], url_path="sync-category")
    def sync_category(self, request, pk=None):
        """Add all missing species from a category and its subcategories."""
        try:
            category_id = uuid.UUID(str(request.data.get("species_category_id")))
        except (ValueError, TypeError, AttributeError):
            raise ValidationError(
                {"species_category_id": "Ange ett giltigt kategori-UUID."}
            )
        try:
            category = SpeciesCategory.objects.get(pk=category_id)
        except SpeciesCategory.DoesNotExist:
            raise ValidationError(
                {"species_category_id": "Ange ett giltigt kategori-UUID."}
            )

        checklist = self.get_object()
        species_added = checklists.add_category_species_to_checklist(
            checklist=checklist,
            category=category,
        )
        return Response(
            {
                "species_category_id": str(category.pk),
                "species_added": species_added,
                "species_count": checklist.items.count(),
            }
        )

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
    pagination_class = StandardPagination
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ["checklist", "species", "is_completed"]

    def get_queryset(self):
        observations = Observation.objects.filter(checklist_items=OuterRef("pk"))
        return (
            ChecklistItem.objects.filter(checklist__user=self.request.user)
            .select_related("checklist", "species")
            .annotate(is_completed=Exists(observations))
        )



class ObservationViewSet(viewsets.ModelViewSet):
    serializer_class = ObservationSerializer
    pagination_class = StandardPagination
    authentication_classes = [SessionAuthentication, TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    filterset_class = ObservationFilter

    def get_queryset(self):
        return (
            Observation.objects.filter(user=self.request.user)
            .select_related("species")
            .prefetch_related(
                Prefetch(
                    "checklist_items",
                    queryset=ChecklistItem.objects.select_related("checklist"),
                )
            )
        )

    def perform_create(self, serializer):
        locales = Locale.objects.filter(user=self.request.user)
        observed_in = None
        location = serializer.validated_data.get("location", {})
        for locale in locales:
            try:
                if point_in_multipolygon(location, locale.geometry):
                    observed_in = locale
            except (IndexError, KeyError, TypeError, ValueError):
                continue

        serializer.save(user=self.request.user, locale=observed_in)

    @action(detail=False, methods=["get"], url_path="by-category")
    def by_category(self, request):
        """Return a paginated, count-only list of actual category groups."""
        grouped = (
            self.filter_queryset(self.get_queryset())
            .order_by()
            .filter(species__category_memberships__isnull=False)
            .values(
                "species__category_memberships__category_id",
                "species__category_memberships__category__label",
                "species__category_memberships__category__taxon_id",
                "species__category_memberships__category__image_url",
                "species__category_memberships__category__is_primary",
            )
            .annotate(obs_count=Count("pk", distinct=True))
            .order_by(
                "-species__category_memberships__category__is_primary",
                "species__category_memberships__category__label",
                "species__category_memberships__category__taxon_id",
                "species__category_memberships__category_id",
            )
        )
        groups = [
            {
                "category": {
                    "id": str(row["species__category_memberships__category_id"]),
                    "label": row["species__category_memberships__category__label"],
                    "taxon_id": row["species__category_memberships__category__taxon_id"],
                    "image_url": row["species__category_memberships__category__image_url"],
                    "is_primary": row[
                        "species__category_memberships__category__is_primary"
                    ],
                },
                "obs_count": row["obs_count"],
            }
            for row in grouped
        ]
        page = self.paginate_queryset(groups)
        return self.get_paginated_response(page)

    @action(
        detail=False,
        methods=["get"],
        url_path=r"by-category/(?P<category_id>[^/.]+)",
    )
    def category_observations(self, request, category_id=None):
        """Return one actual category's observations, paginated."""
        try:
            category = SpeciesCategory.objects.get(pk=uuid.UUID(str(category_id)))
        except (SpeciesCategory.DoesNotExist, ValueError, TypeError, AttributeError):
            raise ValidationError({"category_id": "Ange ett giltigt kategori-UUID."})

        observations = self.filter_queryset(self.get_queryset()).filter(
            species__category_memberships__category=category
        ).distinct()
        page = self.paginate_queryset(observations)
        memberships_by_species = {}
        for (
            species_id,
            attached_category_id,
            label,
            taxon_id,
            image_url,
            is_primary,
        ) in (
            SpeciesCategoryMembership.objects.filter(
                species_id__in={observation.species_id for observation in page}
            )
            .values_list(
                "species_id",
                "category_id",
                "category__label",
                "category__taxon_id",
                "category__image_url",
                "category__is_primary",
            )
            .order_by("category__label", "category__taxon_id", "category_id")
        ):
            memberships_by_species.setdefault(species_id, []).append(
                {
                    "id": str(attached_category_id),
                    "label": label,
                    "taxon_id": taxon_id,
                    "image_url": image_url,
                    "is_primary": is_primary,
                }
            )
        serialized = self.get_serializer(page, many=True).data
        for observation, payload in zip(page, serialized):
            payload["species_categories"] = memberships_by_species.get(
                observation.species_id, []
            )

        response = self.get_paginated_response(serialized)
        response.data["category"] = {
            "id": str(category.pk),
            "label": category.label,
            "taxon_id": category.taxon_id,
            "image_url": category.image_url,
            "is_primary": category.is_primary,
        }
        response.data["obs_count"] = response.data["count"]
        return response

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
