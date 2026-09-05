"""Route plans and durable state for asynchronous stop suggestions."""

import uuid

from django.conf import settings
from django.db import models


class Route(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tempus_routes")
    name = models.CharField(max_length=255)
    planned_date = models.DateField()
    geometry = models.JSONField(default=dict)
    corridor_metres = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("planned_date", "name")

    def __str__(self):
        return self.name


class RouteStop(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    route = models.ForeignKey(Route, on_delete=models.CASCADE, related_name="stops")
    sequence = models.PositiveIntegerField()
    name = models.CharField(max_length=255)
    location = models.JSONField(default=dict)
    planned_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("sequence",)
        constraints = [models.UniqueConstraint(fields=("route", "sequence"), name="tempus_unique_route_stop_sequence")]

    def __str__(self):
        return f"{self.route}: {self.sequence}. {self.name}"


class RouteSuggestionRun(models.Model):
    """Latest background rest-stop calculation for a route, replacing earlier results."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STATUS_CHOICES = [(PENDING, "Pending"), (RUNNING, "Running"), (SUCCEEDED, "Succeeded"), (FAILED, "Failed")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    route = models.OneToOneField(Route, on_delete=models.CASCADE, related_name="suggestion_run")
    params = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    result = models.JSONField(default=list, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.route}: rest-stop suggestions ({self.status})"
