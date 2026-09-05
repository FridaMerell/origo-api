from rest_framework import permissions, viewsets
from rest_framework.permissions import IsAuthenticatedOrReadOnly

from apsis.models import Post
from apsis.serializers import PostSerializer


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
    serializer_class = PostSerializer
    permission_classes = [IsAuthenticatedOrReadOnly, IsAuthorOrReadOnly]
    queryset = Post.objects.all()

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

