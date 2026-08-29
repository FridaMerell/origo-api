import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


DAY_OF_YEAR_VALIDATORS = [MinValueValidator(1), MaxValueValidator(366)]


class Species(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dyntaxa_taxon_id = models.PositiveBigIntegerField(unique=True, db_index=True)
    scientific_name = models.CharField(max_length=255)
    swedish_name = models.CharField(max_length=255, blank=True)
    taxon_rank = models.CharField(max_length=50, blank=True)
    parent_dyntaxa_taxon_id = models.PositiveBigIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    api_data = models.JSONField(default=dict, blank=True)
    # Artfakta landskapstyper: [{"id", "parent_id", "code", "name",
    # "significance"}] where significance is "har" or "stor". Only significant
    # types are listed; anything absent means "no significance". Refreshed on sync.
    landscape_types = models.JSONField(default=list, blank=True)
    # Artfakta biotoper: same shape as landscape_types. Its native scale is
    # "Viktig" / "Utnyttjas", folded onto "stor" / "har"; parent_id gives the
    # biotope hierarchy. Refreshed on sync.
    biotopes = models.JSONField(default=list, blank=True)
    synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("scientific_name",)

    def __str__(self):
        return self.swedish_name or self.scientific_name

    def phenogram_for(self, geo_area=None):
        """This species' stored :class:`Phenogram` for ``geo_area`` (the
        whole-range row when omitted), or ``None`` if none is computed yet."""
        return (
            self.phenograms.filter(geo_area=geo_area).order_by("-years").first()
        )

    def seasonal_status(self, *, geo_area=None, today=None):
        """Where today sits in this species' activity curve - see
        :func:`tempus.services.phenology.phenogram_status`. ``None`` until a
        phenogram exists."""
        from tempus.services import season

        pg = self.phenogram_for(geo_area)
        return season.status_for(pg, today=today) if pg is not None else None

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
    taxon = models.ManyToManyField(
        Species,
        related_name="species_category",
        blank=True,
    )
    taxon_id = models.PositiveBigIntegerField(unique=True,null=True, db_index=True)
    label = models.CharField(max_length=255, blank=True, unique=True)
    image_url = models.URLField(blank=True)
    species = models.ManyToManyField(
        Species,
        related_name="categories",
        blank=True,
    )

    class Meta:
        ordering = ("label",)
        verbose_name_plural = "species categories"

    def __str__(self):
        return self.label or str(self.taxon_id)


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
            models.UniqueConstraint(fields=("user", "species"), name="tempus_unique_user_species_follow"),
        ]

    def __str__(self):
        return f"{self.user} follows {self.species}"


class Phenophase(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=50, unique=True)
    label = models.CharField(max_length=100)

    class Meta:
        ordering = ("label",)

    def __str__(self):
        return self.label


class Source(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    url = models.URLField()
    publisher = models.CharField(max_length=255)
    accessed_at = models.DateTimeField()

    class Meta:
        ordering = ("title",)

    def __str__(self):
        return self.title


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


class Phenogram(models.Model):
    """The stored week-by-week activity curve for a species, and the source of
    its seasonal status.

    Computed from Species Observation System records by
    ``tempus.services.phenogram.get_phenogram`` and rebuilt only on demand.
    One row per (species, area, year-span); ``geo_area`` NULL means the whole
    range (no polygon clip).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    species = models.ForeignKey(Species, on_delete=models.CASCADE, related_name="phenograms")
    geo_area = models.ForeignKey(
        GeoArea, on_delete=models.CASCADE, null=True, blank=True, related_name="phenograms"
    )
    years = models.PositiveSmallIntegerField(default=8)

    # The curve: 52 rows of {"week", "count", "smoothed", "fraction"}.
    weeks = models.JSONField(default=list)
    peak_week = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(52)])
    window_start_week = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(52)])
    window_end_week = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(52)])

    # Day-of-year envelope distilled from the curve; drives seasonal status.
    start_day_of_year = models.PositiveSmallIntegerField(validators=DAY_OF_YEAR_VALIDATORS)
    peak_start_day = models.PositiveSmallIntegerField(null=True, blank=True, validators=DAY_OF_YEAR_VALIDATORS)
    peak_end_day = models.PositiveSmallIntegerField(null=True, blank=True, validators=DAY_OF_YEAR_VALIDATORS)
    end_day_of_year = models.PositiveSmallIntegerField(validators=DAY_OF_YEAR_VALIDATORS)
    confidence = models.FloatField(null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(1)])

    # Provenance.
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
            models.UniqueConstraint(
                fields=("species", "geo_area", "years"),
                condition=models.Q(geo_area__isnull=False),
                name="tempus_unique_phenogram_area",
            ),
            models.UniqueConstraint(
                fields=("species", "years"),
                condition=models.Q(geo_area__isnull=True),
                name="tempus_unique_phenogram_range",
            ),
        ]

    def __str__(self):
        where = self.geo_area if self.geo_area_id else "whole range"
        return f"{self.species} phenogram – {where}"


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
        constraints = [
            models.UniqueConstraint(fields=("route", "sequence"), name="tempus_unique_route_stop_sequence"),
        ]

    def __str__(self):
        return f"{self.route}: {self.sequence}. {self.name}"


class Checklist(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tempus_checklists",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    geo_area = models.ForeignKey(
        GeoArea,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="checklists",
    )
    route = models.ForeignKey(
        Route,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="checklists",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.name


class ChecklistItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    checklist = models.ForeignKey(
        Checklist,
        on_delete=models.CASCADE,
        related_name="items",
    )
    species = models.ForeignKey(
        Species,
        on_delete=models.PROTECT,
        related_name="checklist_items",
    )
    sequence = models.PositiveIntegerField()
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("sequence",)
        constraints = [
            models.UniqueConstraint(
                fields=("checklist", "species"),
                name="tempus_unique_checklist_species",
            ),
            models.UniqueConstraint(
                fields=("checklist", "sequence"),
                name="tempus_unique_checklist_item_sequence",
            ),
        ]

    def __str__(self):
        return f"{self.checklist}: {self.sequence}. {self.species}"


class Observation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tempus_observations")
    species = models.ForeignKey(Species, on_delete=models.PROTECT, related_name="observations")
    checklist_items = models.ManyToManyField(
        ChecklistItem,
        related_name="observations",
        blank=True,
    )
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
