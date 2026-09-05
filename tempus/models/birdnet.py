"""BirdNET devices and their short-lived acoustic detections."""

import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from .species import Species


# The post-save signal publishes here after a new detection commits.
BIRDNET_DETECTION_CHANNEL = "birdnet_detection"


class BirdnetDevice(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    identifier = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=255)
    users = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="birdnet_devices")
    house = models.ForeignKey("verso.House", on_delete=models.SET_NULL, null=True, blank=True, related_name="birdnet_devices")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name", "identifier")

    def __str__(self):
        return f"{self.name} ({self.identifier})"


class BirdnetDetection(models.Model):
    """One incoming detection; records older than 24 hours are purged by a task."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scientific_name = models.CharField(max_length=255)
    species = models.ForeignKey(Species, on_delete=models.SET_NULL, null=True, blank=True, related_name="birdnet_detections")
    confidence = models.FloatField(validators=[MinValueValidator(0.0), MaxValueValidator(1.0)])
    detected_at = models.DateTimeField()
    device = models.ForeignKey(BirdnetDevice, on_delete=models.CASCADE, related_name="detections", db_column="device_id")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-detected_at",)
        indexes = [models.Index(fields=("-detected_at",)), models.Index(fields=("device", "-detected_at"))]

    def __str__(self):
        return f"{self.scientific_name} ({self.confidence:.0%}) @ {self.detected_at:%Y-%m-%d %H:%M}"
