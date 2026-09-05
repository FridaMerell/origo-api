"""Route planning views."""
from datetime import timedelta

from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from tempus import tasks
from tempus.serializers import (
    RouteSerializer,
    RouteStopSerializer,
    RouteSuggestionRunSerializer,
    SuggestedStopsQuerySerializer,
)
from tempus.models import Route, RouteStop, RouteSuggestionRun
from tempus.services import artdatabanken, route_planner


def _is_true(value):
    """Truthiness for a query-string flag (``?sync=true``, ``?refresh=1``)."""
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


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
