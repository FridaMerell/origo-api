"""Read-mostly reference-data views: phenophases, sources, and geo areas."""
import json
import math
from pathlib import Path

from django.conf import settings
from rest_framework import viewsets
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from tempus import models
from tempus.api.common import SharedDataViewSet
from tempus.models import GeoArea, LandCoverFetch, Locale, Phenophase, Source
from tempus.serializers import GeoAreaSerializer, PhenophaseSerializer, SourceSerializer
from tempus.serializers.geography import LocaleSerializer
from tempus.services import geo, lantmateriet, openstreetmap, trafikverket
from tempus.services.locale_sources import SOURCES


def _rate_limited_response(
    exc: lantmateriet.LantmaterietRateLimitedError,
) -> Response:
    """Surface an upstream 429 as our own 429, forwarding Retry-After."""
    response = Response({"detail": str(exc)}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    if exc.retry_after is not None:
        response["Retry-After"] = str(exc.retry_after)
    return response


def _land_cover_with_fallback(
    bbox: tuple[float, float, float, float], *, kinds: set[str] | None = None
) -> dict:
    """Serve the full land-cover layer, or an increasingly coarse Lantmäteriet fallback.

    Full per-surface detail (point lookups, tightly zoomed viewports) is
    tried first and as given. Once the viewport is too large for full
    detail, Lantmäteriet's own ``summary`` (per-surface, forest/agriculture
    only) then ``overview`` (fully dissolved) tiers are used — CORINE is no
    longer used anywhere in this chain, so every response comes from
    Lantmäteriet alone regardless of viewport size.

    ``kinds`` only narrows the full-detail request (it can skip an entire
    collection, verified against the live account - see
    ``lantmateriet.land_cover_map``). The degraded fallbacks are always
    forest/agriculture from ``markytor`` alone and never contain wetland, so
    narrowing them further would not reduce what they fetch.
    """
    try:
        return lantmateriet.land_cover_in_bbox(bbox, kinds=kinds)
    except lantmateriet.LantmaterietMapTooLargeError:
        pass

    try:
        result = lantmateriet.land_cover_summary_in_bbox(bbox)
        return {**result, "degraded": True, "level": "summary"}
    except lantmateriet.LantmaterietAPIError:
        pass

    result = lantmateriet.land_cover_overview_in_bbox(bbox)
    return {**result, "degraded": True, "level": "overview"}


def _parse_bbox(request) -> tuple[float, float, float, float]:
    raw_bbox = request.query_params.get("bbox", "")
    try:
        bbox = tuple(float(value) for value in raw_bbox.split(","))
    except ValueError:
        bbox = ()
    if len(bbox) != 4 or not all(math.isfinite(value) for value in bbox):
        raise ValidationError(
            {"detail": "bbox must be four finite WGS 84 values: minLon,minLat,maxLon,maxLat."}
        )
    min_lon, min_lat, max_lon, max_lat = bbox
    if not (
        -180 <= min_lon < max_lon <= 180
        and -90 <= min_lat < max_lat <= 90
    ):
        raise ValidationError({"detail": "bbox is outside WGS 84 bounds or has invalid order."})
    return bbox


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


class AdministrativeBoundaryViewSet(viewsets.ViewSet):
    """Serve the optional municipality/county map layer by viewport."""

    def list(self, request):
        bbox = _parse_bbox(request)

        try:
            result = lantmateriet.administrative_boundaries_in_bbox(bbox)
        except lantmateriet.LantmaterietConfigurationError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except lantmateriet.LantmaterietRateLimitedError as exc:
            return _rate_limited_response(exc)
        except lantmateriet.LantmaterietAPIError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        requested_kinds = {
            value.strip() for value in request.query_params.get("kinds", "").split(",") if value.strip()
        }
        if requested_kinds:
            result = {
                **result,
                "features": [
                    feature
                    for feature in result["features"]
                    if feature.get("kind") in requested_kinds
                ],
            }
        return Response({"bbox": list(bbox), **result})


class LandCoverViewSet(viewsets.ViewSet):
    """Serve Lantmäteriet land-cover and wetland surfaces by map viewport."""

    def list(self, request):
        bbox = _parse_bbox(request)

        requested_kinds = {
            value.strip() for value in request.query_params.get("kinds", "").split(",") if value.strip()
        }

        try:
            result = _land_cover_with_fallback(bbox, kinds=requested_kinds or None)
        except lantmateriet.LantmaterietConfigurationError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except lantmateriet.LantmaterietMapTooLargeError as exc:
            return Response({"detail": str(exc)}, status=413)
        except lantmateriet.LantmaterietRateLimitedError as exc:
            return _rate_limited_response(exc)
        except lantmateriet.LantmaterietAPIError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        if requested_kinds:
            # Still filtered here too: the degraded fallbacks ignore `kinds`
            # (they are always forest/agriculture from markytor alone), so a
            # wetland-only request that fell back must still end up empty
            # rather than showing land-cover features under the wrong kind.
            result = {
                **result,
                "features": [
                    feature
                    for feature in result["features"]
                    if feature.get("kind") in requested_kinds
                ],
            }
        return Response({"bbox": list(bbox), **result})


class LandCoverByTypeViewSet(viewsets.ViewSet):
    """Serve only the requested ``objekttyp`` land-cover surfaces by viewport.

    Filters server-side via Lantmäteriet's own CQL2 support (see
    ``lantmateriet.land_cover_by_types_in_bbox``) rather than fetching every
    surface in the viewport and discarding the ones the caller did not ask
    for. Full resolution only — same viewport-size limit as the plain
    full-detail land-cover layer, no degraded fallback tiers, since a
    selection this specific has no meaningful coarser substitute.
    """

    def list(self, request):
        bbox = _parse_bbox(request)

        types_param = request.query_params.get("types", "")
        objekttyp_values = tuple(
            value.strip() for value in types_param.split(",") if value.strip()
        )
        if not objekttyp_values:
            raise ValidationError(
                {"detail": "types is required: a comma-separated list of objekttyp values."}
            )

        requested_kinds = {
            value.strip() for value in request.query_params.get("kinds", "").split(",") if value.strip()
        }

        try:
            result = lantmateriet.land_cover_by_types_in_bbox(
                bbox, objekttyp_values, kinds=requested_kinds or None
            )
        except lantmateriet.LantmaterietConfigurationError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except lantmateriet.LantmaterietMapTooLargeError as exc:
            return Response({"detail": str(exc)}, status=413)
        except lantmateriet.LantmaterietRateLimitedError as exc:
            return _rate_limited_response(exc)
        except lantmateriet.LantmaterietAPIError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        if requested_kinds:
            result = {
                **result,
                "features": [
                    feature
                    for feature in result["features"]
                    if feature.get("kind") in requested_kinds
                ],
            }
        return Response({"bbox": list(bbox), "types": list(objekttyp_values), **result})


class CountryOverviewView(APIView):
    """Serve the static whole-country overview: outline, major cities, major
    waterways, a two-tier forest/agriculture land-cover overview, and the
    basemap config, baked into one file ahead of time by
    ``manage.py generate_country_overview``.

    Deliberately not live: the country's outline and land cover barely
    change, so fetching and regenerating them on every request (or even
    every cache period) traded correctness for nothing. This replaces the
    old ``/map/`` aggregator and the ``administrative-boundaries/country/``
    action; per-viewport land-cover/wetland/administrative-boundary layers
    (for closer zoom levels) are fetched directly from their own endpoints
    instead.
    """

    def get(self, request):
        data_path = Path(settings.BASE_DIR) / "tempus" / "data" / "country_overview.json"
        try:
            with data_path.open("r", encoding="utf-8") as handle:
                content = json.load(handle)
        except FileNotFoundError:
            return Response(
                {
                    "detail": (
                        "Country overview has not been generated yet. "
                        "Run manage.py generate_country_overview."
                    )
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        response = Response(content)
        response["Cache-Control"] = "public, max-age=86400"
        return response


class LocaleViewSet(viewsets.ModelViewSet):
    serializer_class=LocaleSerializer

    def get_queryset(self):
        return Locale.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        return serializer.save(user=self.request.user)

    @action(detail=True, methods=["get"], url_path="land-cover")
    def land_cover(self, request, pk=None):
        """Return the Lantmäteriet land-cover feature at a point in this locale."""
        locale = self.get_object()
        try:
            longitude = float(request.query_params["longitude"])
            latitude = float(request.query_params["latitude"])
        except (KeyError, TypeError, ValueError):
            raise ValidationError(
                {"detail": "longitude and latitude query parameters are required numbers."}
            )
        if not all((math.isfinite(longitude), math.isfinite(latitude))):
            raise ValidationError({"detail": "longitude and latitude must be finite numbers."})
        if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
            raise ValidationError({"detail": "longitude or latitude is outside WGS 84 bounds."})
        if not geo.point_in_multipolygon((longitude, latitude), locale.geometry):
            raise ValidationError({"detail": "The point must be within this locale."})

        try:
            feature = lantmateriet.land_cover_at_point(longitude, latitude)
        except lantmateriet.LantmaterietConfigurationError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except lantmateriet.LantmaterietRateLimitedError as exc:
            return _rate_limited_response(exc)
        except lantmateriet.LantmaterietAPIError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        if feature is None:
            return Response(
                {"detail": "No Lantmäteriet land-cover feature was found at this point."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            {
                "locale": locale.pk,
                "point": {"type": "Point", "coordinates": [longitude, latitude]},
                "land_cover": feature["land_cover"],
                "wetland": feature["wetland"],
                "features": feature["features"],
            }
        )

    @action(detail=True, methods=["get"], url_path="land-cover/map")
    def land_cover_map(self, request, pk=None):
        """Return Lantmäteriet map surfaces clipped to this Locale."""
        locale = self.get_object()
        try:
            result = lantmateriet.land_cover_map(locale.geometry)
        except lantmateriet.LantmaterietConfigurationError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except lantmateriet.LantmaterietMapTooLargeError as exc:
            return Response({"detail": str(exc)}, status=413)
        except lantmateriet.LantmaterietRateLimitedError as exc:
            return _rate_limited_response(exc)
        except lantmateriet.LantmaterietAPIError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response({"locale": locale.pk, **result})

    @action(detail=True, methods=["get"], url_path="land-cover/fetch")
    def land_cover_fetch(self, request, pk=None):
        """Return the background-prefetched land-cover/hydrography area for this Locale.

        Separate from ``land-cover/map`` (exact Locale boundary, fetched
        synchronously on request): this reflects the async
        ``tasks.fetch_locale_land_cover`` run for the Locale's bounding box
        padded by ``buffer_metres`` in every direction, kept current by a
        post_save signal whenever the Locale is created or its geometry
        changes. ``status: "missing"`` means no background fetch has run yet
        for this Locale (e.g. it predates this feature) rather than an error.

        ``land_cover`` (Marktäcke Direkt, sea surface included as its "Hav"
        objekttyp) and ``hydrography`` (the separate Hydrografi product:
        lakes, watercourses, coastline) are fetched and returned together.
        """
        locale = self.get_object()
        fetch = LandCoverFetch.objects.filter(locale=locale).first()
        if fetch is None:
            return Response({"locale": locale.pk, "status": "missing"})

        payload = {
            "locale": locale.pk,
            "status": fetch.status,
            "buffer_metres": fetch.buffer_metres,
            "geometry": fetch.geometry,
            "created_at": fetch.created_at,
            "started_at": fetch.started_at,
            "finished_at": fetch.finished_at,
        }
        if fetch.status == LandCoverFetch.SUCCEEDED:
            for source in SOURCES:
                payload[source.key] = getattr(fetch, source.field)
        elif fetch.status == LandCoverFetch.FAILED:
            payload["error"] = fetch.error
        return Response(payload)

    @action(detail=True, methods=["get"], url_path="administrative-boundaries")
    def administrative_boundaries(self, request, pk=None):
        """Return municipal and county boundaries intersecting this Locale."""
        locale = self.get_object()
        try:
            result = lantmateriet.administrative_boundaries(locale.geometry)
        except lantmateriet.LantmaterietConfigurationError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except lantmateriet.LantmaterietRateLimitedError as exc:
            return _rate_limited_response(exc)
        except lantmateriet.LantmaterietAPIError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response({"locale": locale.pk, **result})

    @action(detail=True, methods=["get"], url_path="buildings")
    def buildings(self, request, pk=None):
        """Return OpenStreetMap building footprints clipped to this Locale.

        An exact clip like ``land-cover/map/``: Overpass is queried by the
        Locale's bbox and each footprint is then clipped to the Locale shape
        (see ``services.openstreetmap.buildings_in_geometry``). Overpass errors
        subclass the Lantmäteriet ones, so the same status mapping applies.
        """
        locale = self.get_object()
        try:
            result = openstreetmap.buildings_in_geometry(locale.geometry)
        except lantmateriet.LantmaterietConfigurationError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except lantmateriet.LantmaterietMapTooLargeError as exc:
            return Response({"detail": str(exc)}, status=413)
        except lantmateriet.LantmaterietRateLimitedError as exc:
            return _rate_limited_response(exc)
        except lantmateriet.LantmaterietAPIError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response({"locale": locale.pk, **result})

    @action(detail=True, methods=["get"], url_path="roads")
    def roads(self, request, pk=None):
        """Return current Trafikverket road segments clipped to this Locale.

        Trafikverket's errors subclass the Lantmäteriet ones, so the same
        status mapping applies (503 config, 413 too large, 429, 502).
        """
        locale = self.get_object()
        try:
            result = trafikverket.roads_in_geometry(locale.geometry)
        except lantmateriet.LantmaterietConfigurationError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except lantmateriet.LantmaterietMapTooLargeError as exc:
            return Response({"detail": str(exc)}, status=413)
        except lantmateriet.LantmaterietRateLimitedError as exc:
            return _rate_limited_response(exc)
        except lantmateriet.LantmaterietAPIError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response({"locale": locale.pk, **result})

    @action(detail=True, methods=["get"], url_path="place-names")
    def place_names(self, request, pk=None):
        """Return the nearest Lantmäteriet Ortnamn Direkt place name to a point in this locale.

        Ortnamn Direkt has no radius/bbox search (see
        ``services.lantmateriet``'s Ortnamn section), so - like ``land_cover``
        above - this is a single-point lookup, not a map layer.
        """
        locale = self.get_object()
        try:
            longitude = float(request.query_params["longitude"])
            latitude = float(request.query_params["latitude"])
        except (KeyError, TypeError, ValueError):
            raise ValidationError(
                {"detail": "longitude and latitude query parameters are required numbers."}
            )
        if not all((math.isfinite(longitude), math.isfinite(latitude))):
            raise ValidationError({"detail": "longitude and latitude must be finite numbers."})
        if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
            raise ValidationError({"detail": "longitude or latitude is outside WGS 84 bounds."})
        if not geo.point_in_multipolygon((longitude, latitude), locale.geometry):
            raise ValidationError({"detail": "The point must be within this locale."})

        try:
            place_name = lantmateriet.place_name_nearest(longitude, latitude)
        except lantmateriet.LantmaterietConfigurationError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except lantmateriet.LantmaterietRateLimitedError as exc:
            return _rate_limited_response(exc)
        except lantmateriet.LantmaterietAPIError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        if place_name is None:
            return Response(
                {"detail": "No Lantmäteriet place name was found near this point."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            {
                "locale": locale.pk,
                "point": {"type": "Point", "coordinates": [longitude, latitude]},
                "place_name": place_name,
            }
        )

    @action(detail=True, methods=["get"], url_path="place-names/search")
    def place_names_search(self, request, pk=None):
        """Search Lantmäteriet place names, kept to results inside this Locale.

        Ortnamn Direkt cannot clip to a bbox or Locale boundary itself, so
        this asks it for a name/kommun/län match (server-side, via
        ``lantmateriet.place_names_search``) and then drops any result whose
        point falls outside the Locale's own MultiPolygon - a client-side
        filter on top of Lantmäteriet's own filtering, not a native clip like
        ``land_cover_map``.
        """
        locale = self.get_object()
        namn = request.query_params.get("namn") or None
        lankod = request.query_params.get("lankod") or None
        kommunkod = request.query_params.get("kommunkod") or None
        namntyp_param = request.query_params.get("namntyp", "")
        namntyp = tuple(value.strip() for value in namntyp_param.split(",") if value.strip()) or None
        if not namn and not lankod and not kommunkod:
            raise ValidationError(
                {"detail": "namn, lankod, or kommunkod is required."}
            )

        try:
            max_hits = int(request.query_params.get("maxHits", 100))
        except ValueError:
            raise ValidationError({"detail": "maxHits must be an integer."})

        try:
            result = lantmateriet.place_names_search(
                namn=namn,
                match=request.query_params.get("match") or None,
                lankod=lankod,
                kommunkod=kommunkod,
                namntyp=namntyp,
                max_hits=max_hits,
            )
        except lantmateriet.LantmaterietConfigurationError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except lantmateriet.LantmaterietRateLimitedError as exc:
            return _rate_limited_response(exc)
        except lantmateriet.LantmaterietAPIError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        inside = [
            feature
            for feature in result["features"]
            if feature.get("geometry") is not None
            and geo.point_in_multipolygon(feature["geometry"], locale.geometry)
        ]
        return Response(
            {"locale": locale.pk, "total_upstream": result["total"], "features": inside}
        )
