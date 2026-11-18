from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.http import require_GET
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from caelus.models import EventAlert
from caelus.serializers import EventAlertSerializer
from caelus.services import calendar, iau_mdc, noaa, smhi


@api_view(["GET", "PUT", "DELETE"])
@permission_classes([permissions.IsAuthenticated])
def event_alert(request):
    """The current user's opt-in to warnings before notable sky events.

    ``PUT`` with ``latitude`` and ``longitude`` opts in or moves the position;
    ``DELETE`` opts out. ``GET`` is 404 while the user has not opted in.
    """
    alert = EventAlert.objects.filter(user=request.user).first()
    if request.method == "GET":
        if alert is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(EventAlertSerializer(alert).data)
    if request.method == "DELETE":
        if alert is not None:
            alert.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    serializer = EventAlertSerializer(alert, data=request.data)
    serializer.is_valid(raise_exception=True)
    serializer.save(user=request.user)
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def meteor_showers(request):
    """Return the notable annual meteor showers, from the IAU MDC and IMO."""
    try:
        showers = iau_mdc.get_showers()
    except iau_mdc.IauMdcAPIError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
    return Response(showers)


@api_view(["GET"])
def kp_index(request):
    """Return the planetary Kp index, observed and predicted."""
    try:
        entries = noaa.get_kp_index()
    except noaa.NoaaAPIError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
    return Response(entries)


@require_GET
def calendar_feed(request):
    """Return the coming year's sky events for ``lat`` and ``lon`` as iCalendar.

    A plain Django view: calendar apps ask for ``text/calendar``, which DRF's
    content negotiation would refuse. Open to everyone, since a subscribing
    app has no session.
    """
    try:
        latitude = float(request.GET.get("lat", ""))
        longitude = float(request.GET.get("lon", ""))
    except ValueError:
        return HttpResponseBadRequest("lat and lon are required and must be numbers.")
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return HttpResponseBadRequest("lat or lon is out of range.")
    response = HttpResponse(calendar.calendar_feed(latitude, longitude), content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = 'inline; filename="caelus.ics"'
    return response


@api_view(["GET"])
def cloud_cover(request):
    """Return SMHI's cloud cover forecast for the point in ``lat`` and ``lon``."""
    try:
        latitude = float(request.query_params.get("lat", ""))
        longitude = float(request.query_params.get("lon", ""))
    except ValueError:
        return Response(
            {"detail": "lat and lon are required and must be numbers."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return Response(
            {"detail": "lat or lon is out of range."}, status=status.HTTP_400_BAD_REQUEST
        )
    try:
        forecast = smhi.get_cloud_cover(latitude, longitude)
    except smhi.SmhiAPIError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
    if forecast is None:
        return Response(
            {"detail": "The point is outside SMHI's forecast area."},
            status=status.HTTP_404_NOT_FOUND,
        )
    return Response(forecast)
