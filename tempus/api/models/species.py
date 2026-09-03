import uuid

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Species(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dyntaxa_taxon_id = models.PositiveBigIntegerField(unique=True, db_index=True)
    scientific_name = models.CharField(max_length=255)
    swedish_name = models.CharField(max_length=255, blank=True)
    taxon_rank = models.CharField(max_length=50, blank=True)
    parent_dyntaxa_taxon_id = models.PositiveBigIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    api_data = models.JSONField(default=dict, blank=True)
    significance = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )
    landscape_types = models.JSONField(default=list, blank=True)
    biotopes = models.JSONField(default=list, blank=True)
    synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("scientific_name",)

    def __str__(self):
        return self.swedish_name or self.scientific_name

    def phenogram_for(self, geo_area=None):
        return self.phenograms.filter(geo_area=geo_area).order_by("-years").first()

    def seasonal_status(self, *, geo_area=None, today=None):
        from tempus.services import season

        phenogram = self.phenogram_for(geo_area)
        return season.status_for(phenogram, today=today) if phenogram else None

    def is_in_season(self, *, geo_area=None, today=None):
        status = self.seasonal_status(geo_area=geo_area, today=today)
        return bool(status and status["is_in_season"])

    def is_coming_into_season(self, *, geo_area=None, today=None):
        status = self.seasonal_status(geo_area=geo_area, today=today)
        return bool(status and status["is_coming_into_season"])

    def is_going_out_of_season(self, *, geo_area=None, today=None):
        status = self.seasonal_status(geo_area=geo_area, today=today)
        return bool(status and status["is_going_out_of_season"])
