"""Personal checklists and the observations recorded against them."""

import uuid

from django.conf import settings
from django.db import models

from .geography import GeoArea
from .routes import Route
from .species import Species


class Checklist(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tempus_checklists")
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    geo_area = models.ForeignKey(GeoArea, on_delete=models.SET_NULL, null=True, blank=True, related_name="checklists")
    route = models.ForeignKey(Route, on_delete=models.SET_NULL, null=True, blank=True, related_name="checklists")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    auto_add = models.BooleanField(default=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.name


class ChecklistItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    checklist = models.ForeignKey(Checklist, on_delete=models.CASCADE, related_name="items")
    species = models.ForeignKey(Species, on_delete=models.PROTECT, related_name="checklist_items")
    sequence = models.PositiveIntegerField()
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("sequence",)
        constraints = [
            models.UniqueConstraint(fields=("checklist", "species"), name="tempus_unique_checklist_species"),
            models.UniqueConstraint(fields=("checklist", "sequence"), name="tempus_unique_checklist_item_sequence"),
        ]

    def __str__(self):
        return f"{self.checklist}: {self.sequence}. {self.species}"


class Observation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tempus_observations")
    species = models.ForeignKey(Species, on_delete=models.PROTECT, related_name="observations")
    checklist_items = models.ManyToManyField(ChecklistItem, related_name="observations", blank=True)
    observed_at = models.DateTimeField()
    location = models.JSONField(default=dict)
    count = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-observed_at",)
        indexes = [models.Index(fields=("user", "observed_at"))]

    def __str__(self):
        return f"{self.species} observed at {self.observed_at:%Y-%m-%d %H:%M}"
