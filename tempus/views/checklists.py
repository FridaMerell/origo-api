"""Checklist and observation views."""
import uuid
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

from django.db.models import Count, Exists, OuterRef, Prefetch, Q, Subquery
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import (
    BooleanFilter,
    CharFilter,
    ChoiceFilter,
    DateFilter,
    FilterSet,
    ModelChoiceFilter,
    UUIDFilter,
)
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
    PublicObservationSerializer,
)
from tempus.models import (
    Checklist,
    ChecklistItem,
    Locale,
    Observation,
    SpeciesCategory,
    SpeciesCategoryMembership,
)
from tempus.services import checklists, year_summary


class ObservationFilter(FilterSet):
    """Filters for a user's observations."""

    checklist = UUIDFilter(field_name="checklist_items__checklist_id")
    # Comma-separated Species UUIDs (primary keys) and/or Dyntaxa taxon ids.
    species = CharFilter(method="filter_species")
    # A species category the observed species is a direct member of.
    category = UUIDFilter(method="filter_category")
    observed_from = DateFilter(field_name="observed_at", lookup_expr="date__gte")
    observed_to = DateFilter(field_name="observed_at", lookup_expr="date__lte")
    life_stage = CharFilter(field_name="life_stage", lookup_expr="icontains")
    has_photos = BooleanFilter(method="filter_has_photos")
    ordering = ChoiceFilter(
        choices=[("-observed_at", "Nyast först"), ("observed_at", "Äldst först")],
        method="filter_ordering",
    )

    class Meta:
        model = Observation
        fields = ["species", "checklist_items", "locale"]

    def filter_species(self, queryset, name, value):
        species_ids = []
        taxon_ids = []
        for part in value.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                species_ids.append(uuid.UUID(part))
                continue
            except (ValueError, AttributeError):
                pass
            if not part.isdigit():
                raise ValidationError(
                    {"species": "Ange Species-UUID eller Dyntaxa-taxon-id, kommaseparerade."}
                )
            taxon_ids.append(int(part))
        if not species_ids and not taxon_ids:
            return queryset
        return queryset.filter(
            Q(species_id__in=species_ids) | Q(species__dyntaxa_taxon_id__in=taxon_ids)
        )

    def filter_category(self, queryset, name, value):
        return queryset.filter(
            Exists(
                SpeciesCategoryMembership.objects.filter(
                    species_id=OuterRef("species_id"), category_id=value
                )
            )
        )

    def filter_has_photos(self, queryset, name, value):
        if value is None:
            return queryset
        return queryset.exclude(photos=[]) if value else queryset.filter(photos=[])

    def filter_ordering(self, queryset, name, value):
        if value == "observed_at":
            return queryset.order_by("observed_at", "created_at", "pk")
        return queryset.order_by("-observed_at", "-created_at", "-pk")


def _visible_locales(request):
    return Locale.objects.visible_to(request.user)


class PublicObservationFilter(ObservationFilter):
    """Filters for the all-users observation list (no private checklist filter).

    ``locale`` only accepts public locales and the user's own private ones.
    """

    checklist = None
    locale = ModelChoiceFilter(queryset=_visible_locales)

    class Meta:
        model = Observation
        fields = ["species"]


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
        # The register's search field takes a name or a Dyntaxa taxon number.
        search = request.query_params.get("search", "").strip()
        if search:
            matches = Q(species__swedish_name__icontains=search) | Q(
                species__scientific_name__icontains=search
            )
            if search.isdigit():
                matches |= Q(species__dyntaxa_taxon_id=int(search))
            queryset = queryset.filter(matches)
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



class ObservationCategoryActions:
    """Category grouping over a viewset's own (filtered) observation queryset."""

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


class ObservationViewSet(ObservationCategoryActions, viewsets.ModelViewSet):
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
            .order_by("-observed_at", "-created_at", "-pk")
        )

    def retrieve(self, request, *args, **kwargs):
        """Own observations in full; other users' observations without private data."""
        observation = get_object_or_404(
            Observation.objects.select_related("species").prefetch_related(
                Prefetch(
                    "checklist_items",
                    queryset=ChecklistItem.objects.select_related("checklist"),
                )
            ),
            pk=kwargs["pk"],
        )
        if observation.user_id == request.user.pk:
            serializer = self.get_serializer(observation)
        else:
            serializer = PublicObservationSerializer(
                observation, context=self.get_serializer_context()
            )
        return Response(serializer.data)

    def perform_create(self, serializer):
        if "locale" in serializer.validated_data:
            serializer.save(user=self.request.user)
            return
        observed_in = checklists.locale_containing(
            serializer.validated_data.get("location", {}), user=self.request.user
        )
        serializer.save(user=self.request.user, locale=observed_in)

    @action(detail=False, methods=["get"], url_path="year-summary")
    def year_summary(self, request):
        """The signed-in user's year: ``?year=YYYY``, the current year by default."""
        raw_year = request.query_params.get("year")
        if raw_year is None:
            year = datetime.now(year_summary.STOCKHOLM).year
        elif raw_year.isdigit() and 1900 <= int(raw_year) <= 9999:
            year = int(raw_year)
        else:
            raise ValidationError({"year": "Ange ett årtal, till exempel 2026."})
        return Response(year_summary.year_summary(user=request.user, year=year))

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


class PublicObservationViewSet(ObservationCategoryActions, viewsets.ReadOnlyModelViewSet):
    """All observations from all users, readable by any signed-in user."""

    serializer_class = PublicObservationSerializer
    pagination_class = StandardPagination
    authentication_classes = [SessionAuthentication, TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    filterset_class = PublicObservationFilter

    def get_queryset(self):
        return Observation.objects.select_related("species", "user").order_by(
            "-observed_at", "-created_at", "-pk"
        )
