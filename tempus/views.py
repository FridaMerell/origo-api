from django.db.models import Q
from django_filters.rest_framework import DjangoFilterBackend, FilterSet, NumberFilter
from rest_framework import filters, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from tempus import tasks
from tempus.services import artdatabanken, phenogram, season

from tempus.models import (
    Checklist,
    ChecklistItem,
    GeoArea,
    Observation,
    Phenogram,
    Phenophase,
    Route,
    RouteStop,
    Source,
    Species,
    SpeciesCategory,
    SpeciesFollow,
)
from tempus.serializers import (
    ChecklistItemSerializer,
    ChecklistSerializer,
    GeoAreaSerializer,
    ObservationSerializer,
    PhenogramQuerySerializer,
    PhenogramSerializer,
    PhenophaseSerializer,
    RouteSerializer,
    RegisterSpeciesSerializer,
    GeneratePhenogramsSerializer,
    RouteStopSerializer,
    SourceSerializer,
    SpeciesResyncSerializer,
    SpeciesCategorySerializer,
    SpeciesFollowSerializer,
    SpeciesSearchSerializer,
    SpeciesSerializer,
)


class SharedDataPermission(permissions.BasePermission):
    """Allow authenticated reads and restrict shared-data writes to staff."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.method in permissions.SAFE_METHODS or request.user.is_staff)
        )


class SharedDataViewSet(viewsets.ModelViewSet):
    permission_classes = [SharedDataPermission]


class SpeciesFilter(FilterSet):
    category = NumberFilter(field_name="categories__taxon_id")
    categories__taxon_id = NumberFilter(field_name="categories__taxon_id")

    class Meta:
        model = Species
        fields = [
            "dyntaxa_taxon_id",
            "taxon_rank",
            "is_active",
            "species_category",
        ]


class SpeciesViewSet(SharedDataViewSet):
    queryset = Species.objects.all()
    serializer_class = SpeciesSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_class = SpeciesFilter
    search_fields = ["swedish_name", "scientific_name"]
    lookup_field = "dyntaxa_taxon_id"


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
        return Response(
            self.get_serializer(species).data, status=status.HTTP_201_CREATED
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

        tasks.generate_phenogram.enqueue(
            str(species.pk),
            str(geo_area.pk) if geo_area is not None else None,
            refresh=True,
            **({"years": years} if years is not None else {}),
        )
        return Response(
            {
                "detail": "Phenogram build queued.",
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

        pks = list(selected.values_list("pk", flat=True))
        for species_pk in pks:
            tasks.fan_out_species_phenograms.enqueue(species_pk, refresh=refresh)
        return Response(
            {"detail": "Phenogram generation queued.", "species": len(pks)},
            status=status.HTTP_202_ACCEPTED,
        )


class SpeciesCategoryViewSet(SharedDataViewSet):
    queryset = SpeciesCategory.objects.prefetch_related("taxon").all()
    serializer_class = SpeciesCategorySerializer
    filterset_fields = ["taxon_id"]
    ordering_fields = ["taxon_id", "label", "species_count"]
    ordering = ["taxon_id", "label", "species_count"]
    lookup_field = "taxon_id"


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


class RouteViewSet(viewsets.ModelViewSet):
    serializer_class = RouteSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ["planned_date"]

    def get_queryset(self):
        return Route.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class RouteStopViewSet(viewsets.ModelViewSet):
    serializer_class = RouteStopSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ["route"]

    def get_queryset(self):
        return RouteStop.objects.filter(route__user=self.request.user).select_related("route")


class ChecklistViewSet(viewsets.ModelViewSet):
    serializer_class = ChecklistSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ["start_date", "geo_area", "route"]

    def get_queryset(self):
        return Checklist.objects.filter(user=self.request.user).select_related("geo_area", "route")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class ChecklistItemViewSet(viewsets.ModelViewSet):
    serializer_class = ChecklistItemSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ["checklist", "species"]

    def get_queryset(self):
        return ChecklistItem.objects.filter(checklist__user=self.request.user).select_related("checklist", "species")


class ObservationViewSet(viewsets.ModelViewSet):
    serializer_class = ObservationSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ["species", "checklist_items"]

    def get_queryset(self):
        return Observation.objects.filter(user=self.request.user).prefetch_related("checklist_items")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
