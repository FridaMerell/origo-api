import json
import logging
import time
import uuid
from datetime import timedelta
from urllib.parse import urlsplit, urlunsplit

import psycopg
from django.db import close_old_connections, connection
from django.db.models import Exists, OuterRef, Q, Subquery
from django.http import StreamingHttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django_filters.rest_framework import (
    BooleanFilter,
    DjangoFilterBackend,
    FilterSet,
    NumberFilter,
)
from rest_framework import filters, permissions, status, viewsets
from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.renderers import BaseRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from origo.pagination import StandardPagination
from tempus import tasks
from tempus.services import (
    artdatabanken,
    checklists,
    phenogram,
    route_planner,
    season,
)

from tempus.models import (
    BIRDNET_DETECTION_CHANNEL,
    BirdnetDevice,
    BirdnetDetection,
    Checklist,
    ChecklistItem,
    GeoArea,
    Observation,
    Phenogram,
    Phenophase,
    Route,
    RouteStop,
    RouteSuggestionRun,
    Source,
    Species,
    SpeciesCategory,
    SpeciesFollow,
)
from tempus.serializers import (
    BirdnetDeviceSerializer,
    ChecklistRegisterItemSerializer,
    ChecklistItemSerializer,
    ChecklistSerializer,
    GeoAreaSerializer,
    BirdnetDetectionSerializer,
    ObservationSerializer,
    PhenogramQuerySerializer,
    PhenogramSerializer,
    PhenophaseSerializer,
    RouteSerializer,
    RouteSuggestionRunSerializer,
    SuggestedStopsQuerySerializer,
    RegisterSpeciesSerializer,
    SpeciesChecklistImportSerializer,
    GeneratePhenogramsSerializer,
    RouteStopSerializer,
    SourceSerializer,
    SpeciesResyncSerializer,
    SeasonalOverviewQuerySerializer,
    SeasonalOverviewSerializer,
    SpeciesCategorySerializer,
    SpeciesFollowSerializer,
    SpeciesSearchSerializer,
    SpeciesSerializer,
)


logger = logging.getLogger(__name__)


def _is_true(value):
    """Truthiness for a query-string flag (``?sync=true``, ``?refresh=1``)."""
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


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
    is_followed = BooleanFilter(field_name="is_followed")

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
    pagination_class = StandardPagination

    def get_queryset(self):
        user = self.request.user
        followed = SpeciesFollow.objects.filter(
            species=OuterRef("pk"), user=user
        )
        return super().get_queryset().annotate(is_followed=Exists(followed)).distinct()

    @action(detail=False, methods=["get"], url_path="seasonal-overview")
    def seasonal_overview(self, request):
        """Paginated species currently entering or leaving season in an area.

        The response is built exclusively from stored eight-year phenograms;
        it never starts an Artdatabanken crawl in the request cycle.
        """
        params = SeasonalOverviewQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        opts = params.validated_data

        followed = SpeciesFollow.objects.filter(
            species_id=OuterRef("species_id"), user=request.user
        )
        queryset = (
            Phenogram.objects.filter(
                geo_area=opts["geo_area"],
                years=phenogram.DEFAULT_YEARS,
                record_count__gte=opts["min_records"],
            )
            .select_related("species")
            .annotate(is_followed=Exists(followed))
            .order_by("species__swedish_name", "species__scientific_name")
        )

        wanted = set(opts["status"])
        matches = []
        for row in queryset:
            row._seasonal_status = season.status_for(row)
            if any(season.matches_status(row, item) for item in wanted):
                matches.append(row)

        page = self.paginate_queryset(matches)
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

        pks = [str(pk) for pk in selected.values_list("pk", flat=True)]
        for species_pk in pks:
            tasks.fan_out_species_phenograms.enqueue(species_pk, refresh=refresh)
        return Response(
            {"detail": "Phenogram generation queued.", "species": len(pks)},
            status=status.HTTP_202_ACCEPTED,
        )


class SpeciesCategoryViewSet(SharedDataViewSet):
    queryset = SpeciesCategory.objects.prefetch_related(
        "taxon",
        "memberships__species",
        "children",
    ).all()
    serializer_class = SpeciesCategorySerializer
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

    # A succeeded run with identical params younger than this is reused instead
    # of recomputing (unless the caller passes ?refresh=true).
    SUGGESTION_TTL = timedelta(hours=6)

    @action(detail=True, methods=["get", "post"], url_path="suggested-stops")
    def suggested_stops(self, request, pk=None):
        """The route's rest-stop suggestions - species variety and rarity along
        the corridor, never raw report volume (Artdatabanken observation API).

        ``suggest_rest_stops`` makes dozens of rate-limited API calls, so it
        runs in a background task:

        * ``POST`` starts (or reuses) a computation and returns ``202`` with the
          run ``status``. Params (all optional): ``taxon_id``, ``since_days``,
          ``notable_days``, ``max_detour_m``, ``num_stops``, ``edge_buffer_m``
          (skip stops near either end of the route), ``min_gap_m`` (minimum
          spacing between stops). ``?refresh=true`` forces a recompute even if a
          fresh result exists.
        * ``GET`` returns the current run - poll it for ``status`` and, once
          ``succeeded``, ``result``. ``404`` until the first ``POST``.
          ``?sync=true`` computes inline and returns the stops directly, without
          persisting - for debugging only; it can take minutes and may time out.
        """
        route = self.get_object()

        if request.method == "GET" and _is_true(request.query_params.get("sync")):
            return self._suggested_stops_sync(request, route)

        run = RouteSuggestionRun.objects.filter(route=route).first()

        if request.method == "GET":
            if run is None:
                return Response(
                    {"detail": "No suggestion run for this route yet; POST to start one."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            return Response(RouteSuggestionRunSerializer(run).data)

        # POST - start or reuse a run.
        if not route.geometry:
            raise ValidationError({"geometry": "This route has no geometry."})

        params = SuggestedStopsQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        wanted = dict(params.validated_data)

        fresh_cutoff = timezone.now() - self.SUGGESTION_TTL
        if (
            run is not None
            and not _is_true(request.query_params.get("refresh"))
            and run.status == RouteSuggestionRun.SUCCEEDED
            and run.params == wanted
            and run.finished_at is not None
            and run.finished_at >= fresh_cutoff
        ):
            return Response(RouteSuggestionRunSerializer(run).data)

        run, _ = RouteSuggestionRun.objects.update_or_create(
            route=route,
            defaults={
                "params": wanted,
                "status": RouteSuggestionRun.PENDING,
                "result": [],
                "error": "",
                "started_at": None,
                "finished_at": None,
            },
        )
        tasks.compute_route_suggestions.enqueue(str(route.pk))
        return Response(
            RouteSuggestionRunSerializer(run).data, status=status.HTTP_202_ACCEPTED
        )

    def _suggested_stops_sync(self, request, route):
        if not route.geometry:
            raise ValidationError({"geometry": "This route has no geometry."})
        params = SuggestedStopsQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        try:
            stops = route_planner.suggest_rest_stops(
                route.geometry, route.corridor_metres, **params.validated_data
            )
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)})
        except artdatabanken.ArtdatabankenConfigurationError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except artdatabanken.ArtdatabankenAPIError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({"route": route.pk, "count": len(stops), "stops": stops})


class RouteStopViewSet(viewsets.ModelViewSet):
    serializer_class = RouteStopSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ["route"]

    def get_queryset(self):
        return RouteStop.objects.filter(route__user=self.request.user).select_related("route")


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
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ["species", "checklist_items"]

    def get_queryset(self):
        return Observation.objects.filter(user=self.request.user).prefetch_related("checklist_items")

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


class BirdnetDetectionIngestView(APIView):
    """Ingest endpoint for BirdNET field devices.

    Devices authenticate with a DRF token (``Authorization: Token <key>``).
    One detection per POST; responds 201 with the stored row.
    """

    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = BirdnetDetectionSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


# --- BirdNET live stream -----------------------------------------------------

BIRDNET_STREAM_HEARTBEAT_SECONDS = 15
BIRDNET_STREAM_DEVICE_REFRESH_SECONDS = 60
BIRDNET_STREAM_POLL_SECONDS = 1
BIRDNET_STREAM_BATCH = 200
# OPTIONS keys Django's PostgreSQL backend consumes itself - they are not
# libpq keywords and psycopg.connect() would reject them.
_NON_LIBPQ_OPTIONS = {
    "pool",
    "server_side_binding",
    "isolation_level",
    "assume_role",
}


class ServerSentEventRenderer(BaseRenderer):
    """Lets DRF content negotiation accept ``Accept: text/event-stream``.

    ``EventSource`` sends that Accept header; without a matching renderer the
    request is rejected with 406 before the view runs. The view returns a raw
    ``StreamingHttpResponse``, so ``render`` is never actually called.
    """

    media_type = "text/event-stream"
    format = "event-stream"
    charset = None

    def render(self, data, accepted_media_type=None, renderer_context=None):
        if data is None or isinstance(data, (bytes, str)):
            return data
        # Only reached for an error Response (e.g. 401/403) on this endpoint.
        return json.dumps(data).encode()


def _close_quietly(conn):
    if conn is not None:
        try:
            conn.close()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass


def _birdnet_listen_connection():
    """A dedicated autocommit psycopg connection ``LISTEN``ing for detections.

    Separate from the ORM connection: it blocks in ``LISTEN`` for the whole
    lifetime of one SSE response and must never be shared. Built from the
    default database's settings so it honours ``DATABASE_URL``.
    """
    db = connection.settings_dict
    params = {
        "dbname": db["NAME"] or None,
        "user": db["USER"] or None,
        "password": db["PASSWORD"] or None,
        "host": db["HOST"] or None,
        "port": db["PORT"] or None,
    }
    for key, value in (db.get("OPTIONS") or {}).items():
        if key not in _NON_LIBPQ_OPTIONS and isinstance(value, (str, int)):
            params[key] = value
    conn = psycopg.connect(autocommit=True, **params)
    try:
        conn.execute(f"LISTEN {BIRDNET_DETECTION_CHANNEL}")
    except Exception:
        conn.close()
        raise
    return conn


def _birdnet_user_device_ids(user_id):
    return {
        str(pk)
        for pk in BirdnetDevice.objects.filter(users=user_id).values_list(
            "id", flat=True
        )
    }


def _birdnet_notify_device_id(note):
    try:
        return json.loads(note.payload).get("device_id")
    except (TypeError, ValueError, AttributeError):
        return None


def _birdnet_new_events(user_id, cursor):
    """SSE chunks for detections after ``cursor``; advances ``cursor`` in place."""
    detections = list(
        BirdnetDetection.objects.filter(device__users=user_id)
        .filter(
            Q(created_at__gt=cursor["time"])
            | Q(created_at=cursor["time"], id__gt=cursor["id"])
        )
        .select_related("device", "species")
        .order_by("created_at", "id")[:BIRDNET_STREAM_BATCH]
    )
    chunks = []
    for detection in detections:
        cursor["time"] = detection.created_at
        cursor["id"] = detection.id
        event_id = f"{detection.created_at.isoformat()}|{detection.id}"
        data = json.dumps(BirdnetDetectionSerializer(detection).data)
        chunks.append(f"id: {event_id}\nevent: detection\ndata: {data}\n\n")
    return chunks


class BirdnetDetectionStreamView(APIView):
    """Stream detections for the authenticated user's devices over SSE.

    On PostgreSQL the loop blocks on a ``LISTEN``/``NOTIFY`` signal (channel
    ``birdnet_detection``, emitted by a ``post_save`` signal once the row
    commits) and confirms every wake with a cursor query, so nothing is missed
    or duplicated. It falls back to one-second polling when the backend is not
    PostgreSQL, or when the listen connection cannot be opened or is lost
    mid-stream.
    """

    permission_classes = [permissions.IsAuthenticated]
    renderer_classes = [ServerSentEventRenderer]

    def perform_content_negotiation(self, request, force=False):
        # SSE only - never 406 on a mismatched or absent Accept header.
        return ServerSentEventRenderer(), ServerSentEventRenderer.media_type

    def get(self, request):
        user_id = request.user.pk
        cursor_time, cursor_id = self._initial_cursor(request)

        def event_stream():
            cursor = {"time": cursor_time, "id": cursor_id}
            listen_conn = None
            if connection.vendor == "postgresql":
                try:
                    listen_conn = _birdnet_listen_connection()
                except Exception:  # noqa: BLE001 - degrade to polling
                    logger.warning(
                        "BirdNET SSE: LISTEN connection unavailable; polling",
                        exc_info=True,
                    )

            device_ids = set()
            device_ids_at = 0.0
            last_heartbeat = time.monotonic()
            try:
                close_old_connections()
                for chunk in _birdnet_new_events(user_id, cursor):
                    yield chunk
                last_heartbeat = time.monotonic()

                while True:
                    woke = False
                    now = time.monotonic()

                    if listen_conn is not None:
                        if (
                            now - device_ids_at
                            >= BIRDNET_STREAM_DEVICE_REFRESH_SECONDS
                        ):
                            close_old_connections()
                            device_ids = _birdnet_user_device_ids(user_id)
                            device_ids_at = now
                            woke = True
                        try:
                            for note in listen_conn.notifies(
                                timeout=BIRDNET_STREAM_HEARTBEAT_SECONDS,
                                stop_after=1,
                            ):
                                device_id = _birdnet_notify_device_id(note)
                                if device_id is None or device_id in device_ids:
                                    woke = True
                        except Exception:  # noqa: BLE001 - degrade to polling
                            logger.warning(
                                "BirdNET SSE: LISTEN connection lost; polling",
                                exc_info=True,
                            )
                            _close_quietly(listen_conn)
                            listen_conn = None
                            woke = True
                    else:
                        time.sleep(BIRDNET_STREAM_POLL_SECONDS)
                        woke = True

                    if woke:
                        close_old_connections()
                        chunks = _birdnet_new_events(user_id, cursor)
                        for chunk in chunks:
                            yield chunk
                        if chunks:
                            last_heartbeat = time.monotonic()

                    if (
                        time.monotonic() - last_heartbeat
                        >= BIRDNET_STREAM_HEARTBEAT_SECONDS
                    ):
                        yield ": keep-alive\n\n"
                        last_heartbeat = time.monotonic()
            finally:
                _close_quietly(listen_conn)
                close_old_connections()

        response = StreamingHttpResponse(
            event_stream(),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response

    @staticmethod
    def _initial_cursor(request):
        event_id = request.headers.get("Last-Event-ID", "")
        if "|" in event_id:
            raw_time, raw_id = event_id.rsplit("|", 1)
            parsed_time = parse_datetime(raw_time)
            try:
                parsed_id = uuid.UUID(raw_id)
            except ValueError:
                parsed_id = None
            if parsed_time is not None and parsed_id is not None:
                return parsed_time, parsed_id

        try:
            replay_seconds = max(
                0,
                min(int(request.query_params.get("replay_seconds", 0)), 86_400),
            )
        except (TypeError, ValueError):
            replay_seconds = 0
        return timezone.now() - timedelta(seconds=replay_seconds), uuid.UUID(int=0)


class BirdnetDeviceViewSet(viewsets.ModelViewSet):
    serializer_class = BirdnetDeviceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return (
            BirdnetDevice.objects.filter(users=self.request.user)
            .select_related("house")
            .prefetch_related("users")
            .distinct()
        )

    def perform_create(self, serializer):
        device = serializer.save()
        device.users.add(self.request.user)
