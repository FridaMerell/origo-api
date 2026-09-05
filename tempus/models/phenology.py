"""Stored seasonal activity curves and their background-generation state."""

import uuid

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from .geography import GeoArea
from .species import Species


DAY_OF_YEAR_VALIDATORS = [MinValueValidator(1), MaxValueValidator(366)]


class Phenogram(models.Model):
    """A computed, week-by-week activity curve for one species and area."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    species = models.ForeignKey(Species, on_delete=models.CASCADE, related_name="phenograms")
    geo_area = models.ForeignKey(GeoArea, on_delete=models.CASCADE, null=True, blank=True, related_name="phenograms")
    years = models.PositiveSmallIntegerField(default=8)
    weeks = models.JSONField(default=list)
    peak_week = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(52)])
    window_start_week = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(52)])
    window_end_week = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(52)])
    start_day_of_year = models.PositiveSmallIntegerField(validators=DAY_OF_YEAR_VALIDATORS)
    peak_start_day = models.PositiveSmallIntegerField(null=True, blank=True, validators=DAY_OF_YEAR_VALIDATORS)
    peak_end_day = models.PositiveSmallIntegerField(null=True, blank=True, validators=DAY_OF_YEAR_VALIDATORS)
    end_day_of_year = models.PositiveSmallIntegerField(validators=DAY_OF_YEAR_VALIDATORS)
    confidence = models.FloatField(null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(1)])
    # Per-area rarity and the calculation inputs kept for later diagnosis.
    significance = models.FloatField(null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(1)])
    significance_basis = models.JSONField(default=dict, blank=True)
    smooth_weeks = models.PositiveSmallIntegerField(default=1)
    declustered = models.BooleanField(default=True)
    record_count = models.PositiveIntegerField(default=0)
    record_limit_hit = models.BooleanField(default=False)
    sample_count = models.PositiveIntegerField(default=0)
    years_present = models.PositiveSmallIntegerField(default=0)
    date_from = models.DateField()
    date_to = models.DateField()
    computed_at = models.DateTimeField()

    class Meta:
        ordering = ("-computed_at",)
        indexes = [models.Index(fields=("species", "geo_area"), name="tempus_phenogram_sp_area_idx")]
        constraints = [
            models.UniqueConstraint(fields=("species", "geo_area", "years"), condition=models.Q(geo_area__isnull=False), name="tempus_unique_phenogram_area"),
            models.UniqueConstraint(fields=("species", "years"), condition=models.Q(geo_area__isnull=True), name="tempus_unique_phenogram_range"),
        ]

    def __str__(self):
        where = self.geo_area if self.geo_area_id else "whole range"
        return f"{self.species} phenogram – {where}"


class PhenogramGeneration(models.Model):
    """Durable queue lock for the current species-and-area calculation."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    species = models.ForeignKey(Species, on_delete=models.CASCADE, related_name="phenogram_generations")
    geo_area = models.ForeignKey(GeoArea, on_delete=models.CASCADE, null=True, blank=True, related_name="phenogram_generations")
    years = models.PositiveSmallIntegerField(default=8)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("species", "geo_area"), condition=models.Q(geo_area__isnull=False), name="tempus_unique_phenogram_generation_area"),
            models.UniqueConstraint(fields=("species",), condition=models.Q(geo_area__isnull=True), name="tempus_unique_phenogram_generation_range"),
        ]

    def __str__(self):
        where = self.geo_area if self.geo_area_id else "whole range"
        return f"{self.species} generation – {where} ({self.status})"
