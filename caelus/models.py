from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class EventAlert(models.Model):
    """A user's opt-in to be warned before notable sky events.

    The row existing is the opt-in; deleting it opts out. The position decides
    which location-bound events (eclipses) are visible to the user.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="caelus_event_alert",
    )
    latitude = models.FloatField(
        validators=[MinValueValidator(-90), MaxValueValidator(90)]
    )
    longitude = models.FloatField(
        validators=[MinValueValidator(-180), MaxValueValidator(180)]
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user} at {self.latitude:.1f}, {self.longitude:.1f}"
