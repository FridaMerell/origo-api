import uuid

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex, OpClass, BTreeIndex
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


DAY_OF_YEAR_VALIDATORS = [MinValueValidator(1), MaxValueValidator(366)]

# PostgreSQL LISTEN/NOTIFY channel the BirdNET SSE stream waits on. A post_save
# signal (tempus.signals) emits it once a new BirdnetDetection row commits.
BIRDNET_DETECTION_CHANNEL = "birdnet_detection"


class Species(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dyntaxa_taxon_id = models.PositiveBigIntegerField(unique=True, db_index=True)
    scientific_name = models.CharField(max_length=255)
    swedish_name = models.CharField(max_length=255, blank=True)
    taxon_rank = models.CharField(max_length=50, blank=True)
    parent_dyntaxa_taxon_id = models.PositiveBigIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    api_data = models.JSONField(default=dict, blank=True)
    # How noteworthy a *report* of this taxon is, 0..1 (0 = ubiquitous, 1 = a
    # mega-rarity). Whole-range fallback; the per-area value lives on Phenogram.
    # Derived from the occupied-grid-cell share during phenogram builds - see
    # tempus.services.diversity.significance_from_cells. NOT the Artfakta habitat
    # "significance" nested in landscape_types below.
    significance = models.FloatField(
        null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )
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
        indexes = [
            GinIndex(
                OpClass("swedish_name", name="gin_trgm_ops"),
                name="tempus_species_swe_trgm_idx",
            ),
            BTreeIndex(
                fields=["dyntaxa_taxon_id", 'parent_dyntaxa_taxon_id'],
            ),
        ]

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
    parent_category = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
    )
    is_primary = models.BooleanField(default=False)
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
        through="SpeciesCategoryMembership",
        through_fields=("category", "species"),
    )

    class Meta:
        ordering = ("label",)
        verbose_name_plural = "species categories"

    def __str__(self):
        return self.label or str(self.taxon_id)

    def descendant_categories(self, *, include_self=False):
        """Return this category's descendants, optionally including itself."""
        descendants = []
        stack = [self] if include_self else list(self.children.all())
        seen = set()
        while stack:
            category = stack.pop()
            if category.pk in seen:
                continue
            seen.add(category.pk)
            descendants.append(category)
            stack.extend(list(category.children.all()))
        return descendants

    def effective_species_queryset(self):
        """Species assigned here or to any descendant category."""
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
    category = models.ForeignKey(
        SpeciesCategory,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    species = models.ForeignKey(
        Species,
        on_delete=models.CASCADE,
        related_name="category_memberships",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("category", "species"),
                name="tempus_unique_species_category_membership",
            ),
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
    # Rarity of a report of this species *in this area*, 0..1 - see
    # tempus.services.diversity.significance_from_cells. ``significance_basis``
    # keeps the inputs ({species_cells, area_cells, share, zoom}) for debugging.
    significance = models.FloatField(
        null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )
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


class PhenogramGeneration(models.Model):
    """The durable queue lock for one species and geographic area."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    species = models.ForeignKey(
        Species, on_delete=models.CASCADE, related_name="phenogram_generations"
    )
    geo_area = models.ForeignKey(
        GeoArea,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="phenogram_generations",
    )
    years = models.PositiveSmallIntegerField(default=8)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("species", "geo_area"),
                condition=models.Q(geo_area__isnull=False),
                name="tempus_unique_phenogram_generation_area",
            ),
            models.UniqueConstraint(
                fields=("species",),
                condition=models.Q(geo_area__isnull=True),
                name="tempus_unique_phenogram_generation_range",
            ),
        ]

    def __str__(self):
        where = self.geo_area if self.geo_area_id else "whole range"
        return f"{self.species} generation – {where} ({self.status})"


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


class RouteSuggestionRun(models.Model):
    """The current rest-stop suggestion computation for a route.

    ``suggest_rest_stops`` fans out into dozens of rate-limited Artdatabanken
    calls, so it runs in a background task, not a request. There is exactly one
    row per route (the latest run); recomputing overwrites it in place. The
    frontend POSTs to start a run and polls this row for ``status``/``result``.
    """

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STATUS_CHOICES = [
        (PENDING, "Pending"),
        (RUNNING, "Running"),
        (SUCCEEDED, "Succeeded"),
        (FAILED, "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    route = models.OneToOneField(
        Route, on_delete=models.CASCADE, related_name="suggestion_run"
    )
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
    auto_add = models.BooleanField(default=True)

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


class BirdnetDevice(models.Model):
    """A BirdNET field device shared by users and optionally placed in a house."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    identifier = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=255)
    users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="birdnet_devices",
    )
    house = models.ForeignKey(
        "verso.House",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="birdnet_devices",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name", "identifier")

    def __str__(self):
        return f"{self.name} ({self.identifier})"


class BirdnetDetection(models.Model):
    """A single BirdNET acoustic detection posted by a field device.

    Rows are short-lived: :func:`tempus.tasks.purge_birdnet_detections`
    deletes anything older than 24h. ``scientific_name`` is stored exactly as
    posted; ``species`` is resolved from it best-effort at ingest and left
    null when no :class:`Species` matches.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scientific_name = models.CharField(max_length=255)
    species = models.ForeignKey(
        Species,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="birdnet_detections",
    )
    confidence = models.FloatField(
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
    )
    detected_at = models.DateTimeField()
    device = models.ForeignKey(
        BirdnetDevice,
        on_delete=models.CASCADE,
        related_name="detections",
        db_column="device_id",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-detected_at",)
        indexes = [
            models.Index(fields=("-detected_at",)),
            models.Index(fields=("device", "-detected_at")),
        ]

    def __str__(self):
        return (
            f"{self.scientific_name} ({self.confidence:.0%}) "
            f"@ {self.detected_at:%Y-%m-%d %H:%M}"
        )
