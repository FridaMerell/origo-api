from rest_framework import permissions, status, viewsets
from rest_framework.response import Response

from opus.access import visible_to_user
from opus.models import Bookmark, Excerpt, ReadingProgress
from opus.serializers import BookmarkSerializer, ExcerptSerializer, ReadingProgressSerializer


class ReadingProgressViewSet(viewsets.ModelViewSet):
    serializer_class = ReadingProgressSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = {"user": ["exact"], "work": ["exact"], "position": ["exact", "gte", "lte"]}

    def get_queryset(self):
        return visible_to_user(
            ReadingProgress.objects.select_related("work"), self.request.user, "work__"
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        progress, created = ReadingProgress.objects.update_or_create(
            user=request.user,
            work=serializer.validated_data["work"],
            defaults={
                "position": serializer.validated_data.get("position", 0),
                "character_index": serializer.validated_data.get("character_index"),
            },
        )
        response_serializer = self.get_serializer(progress)
        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

class BookmarkViewSet(viewsets.ModelViewSet):
    serializer_class = BookmarkSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = {
        "user": ["exact"],
        "version": ["exact"],
        "unit": ["exact"],
        "title": ["exact", "icontains"],
    }

    def get_queryset(self):
        return visible_to_user(
            Bookmark.objects.select_related("version__work"), self.request.user, "version__work__"
        )

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class ExcerptViewSet(viewsets.ModelViewSet):
    serializer_class = ExcerptSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = {
        "user": ["exact"],
        "version": ["exact"],
        "unit": ["exact"],
        "title": ["exact", "icontains"],
    }

    def get_queryset(self):
        return visible_to_user(
            Excerpt.objects.select_related("version__work"), self.request.user, "version__work__"
        )

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
