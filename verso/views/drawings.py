"""Drawing and drawing-page views."""
from rest_framework import permissions, viewsets

from verso.models import Drawing, DrawingPage
from verso.serializers import DrawingPageSerializer, DrawingSerializer


class DrawingViewSet(viewsets.ModelViewSet):
    serializer_class = DrawingSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['house', 'venture']

    def get_queryset(self):
        return Drawing.objects.filter(
            house__members=self.request.user,
        ).prefetch_related('pages').distinct()


class DrawingPageViewSet(viewsets.ModelViewSet):
    serializer_class = DrawingPageSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['drawing', 'drawing__house']

    def get_queryset(self):
        return DrawingPage.objects.filter(
            drawing__house__members=self.request.user,
        ).select_related('drawing').distinct()
