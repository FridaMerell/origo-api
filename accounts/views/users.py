"""The user directory and the current user's own account."""
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.db.models import Count, Q
from rest_framework import permissions, status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.serializers import SetPasswordSerializer, UserSerializer
from origo.pagination import StandardPagination

User = get_user_model()


class UserViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['id', 'username', 'email']
    pagination_class = StandardPagination

    def get_queryset(self):
        """Users who share a Flux project or Verso house with the requester."""
        return User.objects.filter(
            Q(projects__members=self.request.user)
            | Q(houses__members=self.request.user)
        ).exclude(pk=self.request.user.pk).annotate(
            open_notifications=Count(
                "notifications",
                filter=Q(notifications__is_read=False),
                distinct=True,
            )
        ).distinct()

class SelfViewSet(viewsets.ModelViewSet):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return User.objects.filter(pk=self.request.user.pk)

    @action(detail=False, methods=['post'], url_path='set-password')
    def set_password(self, request):
        serializer = SetPasswordSerializer(
            data=request.data, context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        update_session_auth_hash(request, request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=['get', 'post', 'delete'])
    def token(self, request):
        """Issue/read (GET, POST), rotate (POST ?rotate=1) or revoke (DELETE)
        the current user's auth token."""
        if request.method == 'DELETE':
            Token.objects.filter(user=request.user).delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        rotate = request.query_params.get('rotate') in ('1', 'true', 'yes')
        if rotate:
            Token.objects.filter(user=request.user).delete()
        token, _ = Token.objects.get_or_create(user=request.user)
        return Response({'token': token.key})
