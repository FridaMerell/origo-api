"""Browser Web Push subscriptions for a user's devices."""

from django.conf import settings
from django.db import models


class WebPushSubscription(models.Model):
    """One ``PushSubscription`` created by a frontend service worker.

    The frontend owns the service worker and the permission prompt; this row is
    what the backend needs to deliver a Web Push message (VAPID) to that device.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="push_subscriptions",
    )
    endpoint = models.URLField(max_length=512, unique=True)
    p256dh = models.CharField(max_length=255)
    auth = models.CharField(max_length=255)
    tenant = models.CharField(max_length=32, blank=True)  # verso|flux|tempus|apsis
    user_agent = models.CharField(max_length=400, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"WebPushSubscription({self.user}, {self.tenant or '-'})"
