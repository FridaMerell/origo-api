"""User-facing notifications across the project's product areas."""

from django.db import models

from .identity import User


class Notification(models.Model):
    DOMAIN_CHOICES = [("verso", "Verso"), ("flux", "Flux"), ("tempus", "Tempus")]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    domain = models.CharField(max_length=20, choices=DOMAIN_CHOICES)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="sent_notifications")

    def __str__(self):
        return f"[{self.domain}] Notification for {self.user}: {self.message}"
