from django.shortcuts import render
import rest_framework.viewsets as viewsets
from rest_framework import permissions
from rest_framework.permissions import IsAuthenticatedOrReadOnly
import apsis.models as models
import apsis.serializers as serializers
class IsAuthorOrReadOnly(permissions.BasePermission):
    """Allow public reads but restrict writes to a post's author or staff."""

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.is_staff or obj.author_id == request.user.pk)
        )


class PostViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.PostSerializer
    permission_classes = [IsAuthenticatedOrReadOnly, IsAuthorOrReadOnly]
    queryset = models.Post.objects.all()

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

