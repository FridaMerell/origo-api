from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    pass


class Notification(models.Model):
    DOMAIN_CHOICES = [
        ("verso", "Verso"),
        ("flux", "Flux"),
    ]

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="notifications"
    )
    domain = models.CharField(max_length=20, choices=DOMAIN_CHOICES)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="sent_notifications"
    )

    def __str__(self):
        return f"[{self.domain}] Notification for {self.user}: {self.message}"
