"""Taxonomy, categories, and user follows."""

import uuid

from django.conf import settings
from django.contrib.postgres.indexes import BTreeIndex, GinIndex, OpClass
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
    # Whole-range report rarity (0..1); per-area values live on Phenogram.
    significance = models.FloatField(
        null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(1)]
    )
    # Significant Artfakta landscape types and biotopes, refreshed on species sync.
    landscape_types = models.JSONField(default=list, blank=True)
    biotopes = models.JSONField(default=list, blank=True)
    synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("scientific_name",)
        indexes = [
            GinIndex(OpClass("swedish_name", name="gin_trgm_ops"), name="tempus_species_swe_trgm_idx"),
            BTreeIndex(fields=["dyntaxa_taxon_id", "parent_dyntaxa_taxon_id"]),
        ]

    def __str__(self):
        return self.swedish_name or self.scientific_name

    def phenogram_for(self, geo_area=None):
        """Return the newest stored activity curve for an area, if present."""
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


class SpeciesCategory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    parent_category = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="children"
    )
    is_primary = models.BooleanField(default=False)
    taxon = models.ManyToManyField(Species, related_name="species_category", blank=True)
    taxon_id = models.PositiveBigIntegerField(unique=True, null=True, db_index=True)
    label = models.CharField(max_length=255, blank=True, unique=True)
    image_url = models.URLField(blank=True)
    species = models.ManyToManyField(
        Species,
        related_name="categories",
        blank=True,
        through="SpeciesCategoryMembership",
        through_fields=("category", "species"),
    )

    class Meta:
        ordering = ("label",)
        verbose_name_plural = "species categories"

    def __str__(self):
        return self.label or str(self.taxon_id)

    def descendant_categories(self, *, include_self=False):
        """Walk the category tree without assuming a maximum nesting depth."""
        descendants = []
        stack = [self] if include_self else list(self.children.all())
        seen = set()
        while stack:
            category = stack.pop()
            if category.pk in seen:
                continue
            seen.add(category.pk)
            descendants.append(category)
            stack.extend(category.children.all())
        return descendants

    def effective_species_queryset(self):
        category_ids = [category.pk for category in self.descendant_categories(include_self=True)]
        return (
            Species.objects.filter(category_memberships__category_id__in=category_ids)
            .distinct()
            .order_by("scientific_name")
        )

    def effective_species_ids(self):
        return list(self.effective_species_queryset().values_list("pk", flat=True))


class SpeciesCategoryMembership(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.ForeignKey(SpeciesCategory, on_delete=models.CASCADE, related_name="memberships")
    species = models.ForeignKey(Species, on_delete=models.CASCADE, related_name="category_memberships")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("category", "species"), name="tempus_unique_species_category_membership"
            )
        ]

    def __str__(self):
        return f"{self.category} - {self.species}"


class SpeciesFollow(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="species_follows")
    species = models.ForeignKey(Species, on_delete=models.CASCADE, related_name="followers")
    priority = models.PositiveSmallIntegerField(default=0)
    notifications_enabled = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("user", "species"), name="tempus_unique_user_species_follow")
        ]

    def __str__(self):
        return f"{self.user} follows {self.species}"
