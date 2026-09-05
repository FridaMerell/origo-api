"""Read and mark-as-read for a user's notifications."""
from rest_framework import mixins, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.models import Notification
from accounts.serializers import NotificationSerializer

# How many recent notifications the lightweight ``summary`` action returns.
NOTIFICATION_SUMMARY_LIMIT = 10


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
