"""Photo, album and tag views."""
import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, permissions, viewsets

from verso.models import Album, Photo, Tag
from verso.serializers import AlbumSerializer, PhotoSerializer, TagSerializer


class PhotoFilter(django_filters.FilterSet):
    album_kind = django_filters.ChoiceFilter(field_name='albums__kind', choices=Album.Kind.choices)

    class Meta:
        model = Photo
        fields = ['house', 'venture', 'task', 'albums', 'album_kind', 'tags', 'people', 'stage']


class PhotoViewSet(viewsets.ModelViewSet):
    serializer_class = PhotoSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_class = PhotoFilter
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    ordering_fields = ['taken_at', 'created_at', 'title']

    def get_queryset(self):
        return Photo.objects.filter(
            house__members=self.request.user,
        ).prefetch_related('albums', 'tags', 'people').distinct()


class AlbumViewSet(viewsets.ModelViewSet):
    serializer_class = AlbumSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['house', 'venture', 'kind']

    def get_queryset(self):
        return Album.objects.filter(house__members=self.request.user).distinct()


class TagViewSet(viewsets.ModelViewSet):
    serializer_class = TagSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['house']

    def get_queryset(self):
        return Tag.objects.filter(house__members=self.request.user).distinct()
