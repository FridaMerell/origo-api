from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from caelus.models import EventAlert
from caelus.serializers import EventAlertSerializer
from caelus.services import iau_mdc, noaa, smhi


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
