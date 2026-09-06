"""Web Push subscription management for the current user's browsers.

Base path matches the frontend constant: ``/api/accounts/push-subscriptions/``.
Session auth + CSRF, exactly like the other writing views.
"""

from django.conf import settings
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from accounts.models import WebPushSubscription
from accounts.push import send_payload_to_user, tenant_root_url
from accounts.serializers import (
    WebPushEndpointSerializer,
    WebPushSubscriptionSerializer,
    WebPushSubscriptionWriteSerializer,
)


class WebPushSubscriptionView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "push-subscriptions"

    def get(self, request):
        subscriptions = request.user.push_subscriptions.filter(is_active=True)
        return Response(
            {
                "vapid_public_key": settings.WEBPUSH_VAPID_PUBLIC_KEY,
                "subscriptions": WebPushSubscriptionSerializer(subscriptions, many=True).data,
            }
        )

    def post(self, request):
        serializer = WebPushSubscriptionWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        defaults = {
            "user": request.user,
            "p256dh": data["keys"]["p256dh"],
            "auth": data["keys"]["auth"],
            "tenant": data["tenant"],
            "user_agent": data["user_agent"],
            "is_active": True,
        }
        subscription, created = WebPushSubscription.objects.update_or_create(
            endpoint=data["endpoint"], defaults=defaults
        )
        code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response({"ok": True}, status=code)

    def delete(self, request):
        serializer = WebPushEndpointSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        WebPushSubscription.objects.filter(
            endpoint=serializer.validated_data["endpoint"], user=request.user
        ).update(is_active=False)
        return Response(status=status.HTTP_204_NO_CONTENT)


class WebPushSubscriptionTestView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "push-test"

    def post(self, request):
        tenant = request.data.get("tenant") or "tempus"
        payload = {
            "title": "Testnotis",
            "body": "Pushnotiser fungerar.",
            "url": tenant_root_url(tenant),
            "tag": "push-test",
            "notificationId": "test",
            "icon": f"/{tenant}/icon.png",
        }
        sent, _dead = send_payload_to_user(request.user, payload)
        return Response({"ok": True, "sent": sent})
