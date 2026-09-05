"""Species, phenogram, and follow views."""
from datetime import date

from django.db.models import Case, Exists, F, IntegerField, OuterRef, Q, Value, When
from django_filters.rest_framework import BooleanFilter, DjangoFilterBackend, FilterSet, NumberFilter
from rest_framework import filters, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from origo.pagination import StandardPagination
from tempus import tasks
from tempus.api.common import SharedDataViewSet
from tempus.serializers import (
    GeneratePhenogramsSerializer,
    PhenogramQuerySerializer,
    PhenogramSerializer,
    RegisterSpeciesSerializer,
    SeasonalOverviewQuerySerializer,
    SeasonalOverviewSerializer,
    SpeciesCategoryListSerializer,
    SpeciesCategorySerializer,
    SpeciesChecklistImportSerializer,
    SpeciesFollowSerializer,
    SpeciesResolveRequestSerializer,
    SpeciesResyncSerializer,
    SpeciesSearchSerializer,
    SpeciesSerializer,
)
from tempus.models import Phenogram, Species, SpeciesCategory, SpeciesFollow
from tempus.services import artdatabanken, phenogram, season


def _day_of_year_in_span(start_field, end_field, day):
    """A ``Q`` expression for an inclusive day-of-year span that may wrap."""
    return (
        Q(**{f"{start_field}__lte": F(end_field)})
        & Q(**{f"{start_field}__lte": day})
        & Q(**{f"{end_field}__gte": day})
    ) | (
        Q(**{f"{start_field}__gt": F(end_field)})
        & (Q(**{f"{start_field}__lte": day}) | Q(**{f"{end_field}__gte": day}))
    )


def _day_of_year_within(field, day, days):
    """A ``Q`` expression for a date-field value within ``days`` days ahead."""
    end = day + days
    if end <= 366:
        return Q(**{f"{field}__gte": day, f"{field}__lte": end})
    return Q(**{f"{field}__gte": day}) | Q(**{f"{field}__lte": end - 366})


class SpeciesFilter(FilterSet):
    # Species assigned to this category *or any of its subcategories* -
    # mirrors SpeciesCategory.effective_species_ids so a category page's
    # species list matches its species_count.
    category = NumberFilter(method="filter_category")
    # Keep the legacy query parameter used by the frontend, but give it the
    # same subtree semantics as ``category``.  A parent category should expose
    # species assigned directly to it as well as species assigned to any child.
    categories__taxon_id = NumberFilter(method="filter_category")
    is_followed = BooleanFilter(field_name="is_followed")

    def filter_category(self, queryset, name, value):
        try:
            category = SpeciesCategory.objects.get(taxon_id=value)
        except SpeciesCategory.DoesNotExist:
            return queryset.none()
        category_ids = [
            c.pk for c in category.descendant_categories(include_self=True)
        ]
        return queryset.filter(
            category_memberships__category_id__in=category_ids
        ).distinct()

    class Meta:
        model = Species
        fields = [
            "dyntaxa_taxon_id",
            "taxon_rank",
            "is_active",
            "species_category",
        ]


class SpeciesViewSet(SharedDataViewSet):
    # Cap on followed species shown when no status filter is given, so an
    # active watcher's out-of-season follows don't crowd the overview.
    MAX_FOLLOWED_WITHOUT_STATUS = 15

    queryset = Species.objects.all()
    serializer_class = SpeciesSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_class = SpeciesFilter
    search_fields = ["swedish_name"]
    lookup_field = "dyntaxa_taxon_id"
    pagination_class = StandardPagination

    def get_queryset(self):
        user = self.request.user
        followed = SpeciesFollow.objects.filter(
            species=OuterRef("pk"), user=user
        )
        # ``api_data`` is retained for refresh bookkeeping but is not part of
        # the public response. Avoid loading it for every row in the catalogue.
        # The EXISTS annotation cannot introduce duplicate Species rows, so a
        # DISTINCT would only add unnecessary work to both the page and count
        # queries.
        return super().get_queryset().defer("api_data").annotate(
            is_followed=Exists(followed)
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="resolve",
        permission_classes=[permissions.IsAuthenticated],
    )
    def resolve(self, request):
        """Return the requested Tempus species without changing any state."""
        request_serializer = SpeciesResolveRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        species = self.get_queryset().filter(
            id__in=request_serializer.validated_data["ids"]
        )
        return Response(self.get_serializer(species, many=True).data)

    @action(detail=False, methods=["get"], url_path="seasonal-overview")
    def seasonal_overview(self, request):
        """Paginated species with a useful current seasonal signal.

        Prefer the selected area's stored eight-year curve. When that is absent,
        fall back to the species' whole-range curve and label the source so the
        client can explain the lower geographic precision. No request starts an
        Artdatabanken crawl.
        """
        params = SeasonalOverviewQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        opts = params.validated_data
        geo_area = opts["geo_area"]

        followed = SpeciesFollow.objects.filter(
            species_id=OuterRef("species_id"), user=request.user
        )
        queryset = (
            Phenogram.objects.filter(years=phenogram.DEFAULT_YEARS)
            .select_related("species")
            # The overview only needs the condensed seasonal envelope. Avoid
            # fetching every 52-week curve and provenance payload while
            # evaluating all candidate rows before pagination.
            .defer("weeks", "significance_basis", "species__api_data")
            # Phenogram's default ordering is -computed_at, but this action
            # applies its own relevance ordering below.
            .order_by()
        )
        # No area selected ("whole Sweden") -> only the whole-range curves
        # exist to show; a selected area also falls back to those.
        queryset = queryset.filter(
            Q(geo_area=geo_area) | Q(geo_area__isnull=True)
            if geo_area is not None
            else Q(geo_area__isnull=True)
        )
        queryset = queryset.annotate(is_followed=Exists(followed))
        if "is_followed" in opts:
            queryset = queryset.filter(is_followed=opts["is_followed"])

        wanted = opts["status"]
        widened_for_followed = (
            opts.get("is_followed") and "status" not in request.query_params
        )
        if widened_for_followed:
            wanted = [
                "at_peak",
                "in_season",
                "coming_into_season",
                "going_out_of_season",
                "out_of_season",
            ]
        today = date.today().timetuple().tm_yday
        in_season = _day_of_year_in_span(
            "start_day_of_year", "end_day_of_year", today
        )
        at_peak = (
            Q(peak_start_day__isnull=False, peak_end_day__isnull=False)
            & _day_of_year_in_span("peak_start_day", "peak_end_day", today)
        )
        coming_into_season = ~in_season & _day_of_year_within(
            "start_day_of_year", today, 21
        )
        going_out_of_season = in_season & _day_of_year_within(
            "end_day_of_year", today, 14
        )
        status_conditions = {
            "at_peak": at_peak,
            "in_season": in_season,
            "coming_into_season": coming_into_season,
            "going_out_of_season": going_out_of_season,
            "out_of_season": ~in_season & ~coming_into_season,
        }

        # One card per species. A local curve always beats the whole-range
        # fallback, even if the fallback has more records.
        if geo_area is not None:
            local_curve_exists = Phenogram.objects.filter(
                species_id=OuterRef("species_id"),
                geo_area=geo_area,
                years=phenogram.DEFAULT_YEARS,
            )
            queryset = queryset.annotate(
                has_local_curve=Exists(local_curve_exists),
                scope_rank=Case(
                    When(geo_area=geo_area, then=Value(0)),
                    default=Value(1),
                    output_field=IntegerField(),
                ),
            ).filter(Q(geo_area=geo_area) | Q(geo_area__isnull=True, has_local_curve=False))
        else:
            queryset = queryset.annotate(
                scope_rank=Value(1, output_field=IntegerField())
            )

        queryset = queryset.annotate(
            seasonal_rank=Case(
                *[
                    When(status_conditions[item], then=Value(index))
                    for index, item in enumerate(wanted)
                ],
                default=Value(len(wanted)),
                output_field=IntegerField(),
            ),
            low_confidence_rank=Case(
                When(record_count__lt=opts["min_records"], then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            ),
        ).filter(seasonal_rank__lt=len(wanted))
        queryset = queryset.order_by(
            "-is_followed",
            "seasonal_rank",
            "scope_rank",
            "low_confidence_rank",
            "-record_count",
            "species__swedish_name",
            "species__scientific_name",
        )
        if widened_for_followed:
            queryset = queryset[: self.MAX_FOLLOWED_WITHOUT_STATUS]
        page = self.paginate_queryset(queryset)
        for row in page:
            row._phenogram_scope = (
                "selected_area" if geo_area is not None and row.geo_area_id == geo_area.pk
                else "whole_range"
            )
            row._is_low_confidence = row.record_count < opts["min_records"]
            row._seasonal_status = season.status_for(row)
        serializer = SeasonalOverviewSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @action(detail=False, methods=["post"])
    def register(self, request):
        """Fetch a taxon from the Artdatabanken APIs and save it.

        Body: ``{"species_category": <id>, "dyntaxa_taxon_id": <int>}``.
        """
        payload = RegisterSpeciesSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            species = artdatabanken.register_species(
                category=payload.validated_data["species_category"],
                dyntaxa_taxon_id=payload.validated_data["dyntaxa_taxon_id"],
            )
        except artdatabanken.ArtdatabankenConfigurationError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except artdatabanken.ArtdatabankenAPIError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        if species is None:
            return Response(
                {"detail": "Taxonet saknar ett svenskt namn och importerades inte."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            self.get_serializer(species).data, status=status.HTTP_201_CREATED
        )

    @action(detail=False, methods=["post"], url_path="import-checklist")
    def import_checklist(self, request):
        """Validate a CSV checklist and queue every taxon for registration.

        Multipart body: ``species_category`` (category UUID) and ``file``. The
        CSV must be UTF-8 and contain a ``Taxon id`` column; semicolon-, comma-
        and tab-delimited exports are accepted.
        """
        payload = SpeciesChecklistImportSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        category = payload.validated_data["species_category"]
        taxon_ids = payload.validated_data["taxon_ids"]

        tasks.import_species_checklist.enqueue(str(category.pk), taxon_ids)

        return Response(
            {
                "detail": (
                    "Species import queued. Phenograms will be scheduled after "
                    "all taxa have been processed."
                ),
                "category": str(category.pk),
                "queued": len(taxon_ids),
                "batch_tasks": 1,
                "duplicates_ignored": payload.validated_data["duplicate_count"],
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=["post"])
    def resync(self, request, dyntaxa_taxon_id=None):
        """Refresh this species' cache from Dyntaxa and Artfakta.

        Re-pulls taxonomy, species information, *landskapstyper* and *biotoper*
        for the stored ``dyntaxa_taxon_id`` and bumps ``synced_at``. Artfakta
        data is best-effort - its absence never blocks the refresh. Staff only.
        """
        species = self.get_object()
        try:
            species = artdatabanken.upsert_species(species.dyntaxa_taxon_id)
        except artdatabanken.ArtdatabankenConfigurationError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except artdatabanken.ArtdatabankenAPIError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(self.get_serializer(species).data)

    @action(detail=False, methods=["post"], url_path="resync")
    def resync_bulk(self, request):
        """Refresh many species from Dyntaxa and Artfakta in one call. Staff only.

        Body (all optional): ``taxa`` (list of dyntaxa ids), ``all`` (true =
        every species), or neither to take species not synced within
        ``older_than_days`` (default 30) plus any never synced. Runs
        synchronously - one atomic upsert per species - so scope it. Returns
        ``{"synced": [...], "failed": [{"dyntaxa_taxon_id", "detail"}]}``.
        """
        params = SpeciesResyncSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        opts = params.validated_data

        if opts.get("taxa"):
            selected = Species.objects.filter(
                dyntaxa_taxon_id__in=opts["taxa"]
            ).order_by("scientific_name")
        elif opts.get("missing"):
            condition = Q()
            for field in opts["missing"]:
                condition |= Q(**{field: []}) | Q(**{f"{field}__isnull": True})
            selected = Species.objects.filter(condition).order_by("scientific_name")
        elif opts["all"]:
            selected = Species.objects.order_by("scientific_name")
        else:
            kwargs = {}
            if "older_than_days" in opts:
                kwargs["older_than_days"] = opts["older_than_days"]
            selected = artdatabanken.stale_species(**kwargs)

        synced, failed = [], []
        try:
            for taxon_id, _species, error in artdatabanken.resync_species_batch(selected):
                if error is None:
                    synced.append(taxon_id)
                else:
                    failed.append(
                        {"dyntaxa_taxon_id": taxon_id, "detail": str(error)}
                    )
        except artdatabanken.ArtdatabankenConfigurationError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        return Response({"synced": synced, "failed": failed})

    @action(detail=False, methods=["get"])
    def search(self, request):
        """Search the Dyntaxa taxon service by name: ``?q=<text>``.

        Pass ``?under_taxon_id=<dyntaxa id>`` (e.g. a category's ``taxon_id``) to
        restrict results to taxa at or below that taxon in the hierarchy, and
        ``?limit=<n>`` to cap the number of results.
        """
        params = SpeciesSearchSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        call_kwargs = {"under_taxon_id": params.validated_data.get("under_taxon_id")}
        if params.validated_data.get("limit") is not None:
            call_kwargs["limit"] = params.validated_data["limit"]
        try:
            results = artdatabanken.search_taxa(
                params.validated_data["q"], **call_kwargs
            )
        except artdatabanken.ArtdatabankenConfigurationError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except artdatabanken.ArtdatabankenAPIError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(results)

    @action(
        detail=True,
        methods=["get", "post"],
        permission_classes=[permissions.IsAuthenticated],
    )
    def phenogram(self, request, dyntaxa_taxon_id=None):
        """This species' stored seasonal activity curve (ISO week 1..52).

        ``GET`` reads the persisted ``Phenogram`` row and never crawls - safe on
        every render. If no row exists yet it returns ``202`` and enqueues a
        background build. ``POST`` with ``refresh: true`` always enqueues a
        rebuild and returns ``202``. Identifying options (query string for GET,
        body for POST): ``geo_area`` (a GeoArea id; omit for the whole range)
        and ``years`` (default 8).
        """
        species = self.get_object()
        source = request.data if request.method == "POST" else request.query_params
        params = PhenogramQuerySerializer(data=source)
        params.is_valid(raise_exception=True)
        opts = params.validated_data
        geo_area = opts.get("geo_area")
        years = opts.get("years")
        refresh = bool(opts.get("refresh"))

        row = phenogram.get_phenogram(
            species, geo_area, create=False,
            **({"years": years} if years is not None else {}),
        )
        if row is not None and not refresh:
            return Response(PhenogramSerializer(row).data)

        _generation, queued = tasks.enqueue_phenogram_generation(
            str(species.pk),
            str(geo_area.pk) if geo_area is not None else None,
            refresh=True,
            **({"years": years} if years is not None else {}),
        )
        return Response(
            {
                "detail": (
                    "Phenogram build queued."
                    if queued
                    else "A phenogram build is already queued or running."
                ),
                "phenogram": PhenogramSerializer(row).data if row is not None else None,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=False, methods=["post"], url_path="generate-phenograms")
    def generate_phenograms(self, request):
        """Enqueue phenogram generation for every GeoArea, per species. Staff only.

        Body (all optional): ``taxa`` (list of dyntaxa ids), ``all`` (``true`` =
        every species), or neither for every species. ``refresh`` (default
        ``true``) rebuilds existing curves too. One fan-out task per species is
        queued; each then queues one build per GeoArea. Returns ``202``.
        """
        params = GeneratePhenogramsSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        opts = params.validated_data
        refresh = opts["refresh"]

        if opts.get("taxa"):
            selected = Species.objects.filter(dyntaxa_taxon_id__in=opts["taxa"])
        else:
            selected = Species.objects.all()

        pks = [str(pk) for pk in selected.values_list("pk", flat=True)]
        for species_pk in pks:
            tasks.fan_out_species_phenograms.enqueue(species_pk, refresh=refresh)
        return Response(
            {"detail": "Phenogram generation queued.", "species": len(pks)},
            status=status.HTTP_202_ACCEPTED,
        )


class PhenogramViewSet(viewsets.ReadOnlyModelViewSet):
    """Browse stored phenograms and their current seasonal status.

    ``GET /phenograms/`` lists every computed curve; filter with ``?species=``,
    ``?geo_area=``, ``?years=`` and ``?status=`` to answer "which species are in
    season / coming into season / going out of season" right now. ``status``
    accepts ``in_season`` / ``coming_into_season`` / ``going_out_of_season`` /
    ``at_peak`` / ``out_of_season`` (the overlapping view) or one of the exact
    ``status`` values. Reads only - rebuild a curve via the species
    ``phenogram`` action.
    """

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = PhenogramSerializer
    queryset = Phenogram.objects.select_related("species", "geo_area")
    filterset_fields = ["species", "geo_area", "years"]

    def get_queryset(self):
        queryset = super().get_queryset()
        wanted = self.request.query_params.get("status")
        if wanted:
            if not season.valid_status(wanted):
                raise ValidationError({"status": f"Unknown status {wanted!r}."})
            matched = season.filter_by_status(queryset, wanted)
            queryset = queryset.filter(pk__in=[pg.pk for pg in matched])
        return queryset

    def list(self, request, *args, **kwargs):
        # ``?status=`` can't be a plain SQL WHERE (the day-of-year window may
        # wrap the year boundary), so season.filter_by_status evaluates it in
        # Python. Apply ?species=/?geo_area=/?years= first to shrink what that
        # Python pass has to look at, then serialize the already-hydrated
        # matches directly instead of re-querying by their pks (get_queryset
        # takes that pk__in round trip for the retrieve/detail path, where a
        # second, cheap, single-row query is the right trade-off).
        queryset = self.filter_queryset(super().get_queryset())
        wanted = request.query_params.get("status")
        if not wanted:
            serializer = self.get_serializer(queryset, many=True)
            return Response(serializer.data)
        if not season.valid_status(wanted):
            raise ValidationError({"status": f"Unknown status {wanted!r}."})
        matched = season.filter_by_status(queryset, wanted)
        serializer = self.get_serializer(matched, many=True)
        return Response(serializer.data)


class SpeciesFollowViewSet(viewsets.ModelViewSet):
    serializer_class = SpeciesFollowSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ["species", "priority", "notifications_enabled"]

    def get_queryset(self):
        return SpeciesFollow.objects.filter(user=self.request.user).select_related("species")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def perform_update(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=False, methods=["get"], permission_classes=[permissions.IsAuthenticated])
    def my_follows(self, request):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["delete"], permission_classes=[permissions.IsAuthenticated])
    def unfollow(self, request):
        """Remove the current user's follow for a species, addressed by its
        Dyntaxa taxon id (``DELETE /species-follows/unfollow/?species=<id>``)."""
        species = request.query_params.get("species")
        if not species or not str(species).isdigit():
            raise ValidationError({"species": "Ange artens Dyntaxa-taxon-id."})
        deleted, _ = (
            self.get_queryset().filter(species__dyntaxa_taxon_id=species).delete()
        )
        if not deleted:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


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
