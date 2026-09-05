"""Geographic reference data used by seasonal and route features."""

import uuid

from django.db import models


class GeoArea(models.Model):
    class Kind(models.TextChoices):
        COUNTRY = "country", "Land"
        COUNTY = "county", "Län"
        PROVINCE = "province", "Landskap"
        NATURE_RESERVE = "nature_reserve", "Naturreservat"
        BIOLOGICAL_AREA = "biological_area", "Biologiskt område"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    kind = models.CharField(max_length=30, choices=Kind.choices)
    country_code = models.CharField(max_length=2)
    geometry = models.JSONField(default=dict)

    class Meta:
        ordering = ("name",)
        indexes = [models.Index(fields=("kind", "country_code"))]

    def __str__(self):
        return f"{self.name} ({self.get_kind_display()})"
