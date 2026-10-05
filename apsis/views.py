import re

from rest_framework import permissions, status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response

from apsis.models import Post
from apsis.serializers import PostSerializer
from apsis.services import svenska_kyrkan


class PostViewSet(viewsets.ModelViewSet):
    """Public reads; any authenticated user may create, change or delete any post."""

    serializer_class = PostSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    queryset = Post.objects.all()

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)


def _svenska_kyrkan_error_response(exc):
    if isinstance(exc, svenska_kyrkan.SvenskaKyrkanConfigurationError):
        return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def place_search(request):
    """Search Svenska kyrkan's churches and chapels by name."""
    try:
        places = svenska_kyrkan.search_places(request.query_params.get("q", ""))
    except (
        svenska_kyrkan.SvenskaKyrkanConfigurationError,
        svenska_kyrkan.SvenskaKyrkanAPIError,
    ) as exc:
        return _svenska_kyrkan_error_response(exc)
    return Response(places)


PLACE_ID_PATTERN = re.compile(r"^[0-9A-Za-z-]+$")
MAX_SUMMARY_IDS = 200


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def place_summaries(request):
    """Return the summaries of the places in ``ids``, keyed by ID.

    Public like the posts themselves: it is what a list of posts shows.
    """
    ids = [
        place_id
        for place_id in request.query_params.get("ids", "").split(",")
        if PLACE_ID_PATTERN.match(place_id)
    ][:MAX_SUMMARY_IDS]
    try:
        summaries = svenska_kyrkan.get_place_summaries(ids)
    except (
        svenska_kyrkan.SvenskaKyrkanConfigurationError,
        svenska_kyrkan.SvenskaKyrkanAPIError,
    ) as exc:
        return _svenska_kyrkan_error_response(exc)
    return Response(summaries)


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def place_detail(request, place_id):
    """Return the live Svenska kyrkan details of a connected church."""
    try:
        place = svenska_kyrkan.get_place(place_id)
    except (
        svenska_kyrkan.SvenskaKyrkanConfigurationError,
        svenska_kyrkan.SvenskaKyrkanAPIError,
    ) as exc:
        return _svenska_kyrkan_error_response(exc)
    if place is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response(place)

