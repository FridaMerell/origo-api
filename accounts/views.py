from django.contrib.auth import get_user_model, login, logout
from django.db.models import Q
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Notification
from accounts.serializers import LoginSerializer, NotificationSerializer, UserSerializer

User = get_user_model()

# How many recent notifications the lightweight ``summary`` action returns.
NOTIFICATION_SUMMARY_LIMIT = 10


@method_decorator(ensure_csrf_cookie, name='dispatch')
class CSRFTokenView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response({'csrfToken': get_token(request)})


class LoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        login(request, serializer.validated_data['user'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)


class UserViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['id', 'username', 'email']

    def get_queryset(self):
        """Users who share a Flux project or Verso house with the requester."""
        return User.objects.filter(
            Q(projects__members=self.request.user)
            | Q(houses__members=self.request.user)
        ).exclude(pk=self.request.user.pk).distinct()

class SelfViewSet(viewsets.ModelViewSet):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return User.objects.filter(pk=self.request.user.pk)


class NotificationViewSet(mixins.ListModelMixin,
                          mixins.RetrieveModelMixin,
                          viewsets.GenericViewSet):
    """Read + mark-as-read for the current user's notifications.

    Poll ``GET /api/accounts/notifications/summary/`` about once a minute for the
    unread count and the latest few rows; use the list endpoint for the full
    list and ``?unread=true`` to filter.
    """

    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['domain', 'is_read']

    def get_queryset(self):
        qs = Notification.objects.filter(user=self.request.user).order_by('-created_at')
        unread = self.request.query_params.get('unread')
        if unread is not None and unread.lower() in ('1', 'true', 'yes'):
            qs = qs.filter(is_read=False)
        return qs

    @action(detail=False, methods=['get'])
    def summary(self, request):
        qs = Notification.objects.filter(user=request.user).order_by('-created_at')
        latest = qs[:NOTIFICATION_SUMMARY_LIMIT]
        return Response({
            'unread_count': qs.filter(is_read=False).count(),
            'latest': NotificationSerializer(latest, many=True).data,
        })

    @action(detail=True, methods=['post'])
    def read(self, request, pk=None):
        notification = self.get_object()
        if not notification.is_read:
            notification.is_read = True
            notification.save(update_fields=['is_read'])
        return Response(NotificationSerializer(notification).data)

    @action(detail=False, methods=['post'], url_path='read-all')
    def read_all(self, request):
        updated = Notification.objects.filter(
            user=request.user, is_read=False,
        ).update(is_read=True)
        return Response({'marked_read': updated})
