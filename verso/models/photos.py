"""Photos for a house: everyday snapshots, project progress (before/after), and
later an image bank (history research, old family photos, maps). Files are hosted
by the frontend; only their URLs are stored here."""

from django.conf import settings
from django.db import models

from .history import DatePrecision
from .homes import House
from .ventures import Venture, VentureTask


class Tag(models.Model):
    house = models.ForeignKey(House, on_delete=models.CASCADE, related_name="photo_tags")
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["house", "name"], name="verso_unique_tag_per_house")]

    def __str__(self):
        return self.name


class Album(models.Model):
    class Kind(models.TextChoices):
        GENERAL = "general", "General"
        PROGRESS = "progress", "Project progress"
        HISTORY = "history", "History research"

    house = models.ForeignKey(House, on_delete=models.CASCADE, related_name="albums")
    venture = models.ForeignKey(Venture, on_delete=models.SET_NULL, related_name="albums", null=True, blank=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.GENERAL)
    cover = models.ForeignKey("Photo", on_delete=models.SET_NULL, related_name="+", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Photo(models.Model):
    class Stage(models.TextChoices):
        BEFORE = "before", "Before"
        DURING = "during", "During"
        AFTER = "after", "After"

    house = models.ForeignKey(House, on_delete=models.CASCADE, related_name="photos")
    venture = models.ForeignKey(Venture, on_delete=models.SET_NULL, related_name="photos", null=True, blank=True)
    task = models.ForeignKey(VentureTask, on_delete=models.SET_NULL, related_name="photos", null=True, blank=True)
    albums = models.ManyToManyField(Album, related_name="photos", blank=True)
    tags = models.ManyToManyField(Tag, related_name="photos", blank=True)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="verso_photos")

    url = models.URLField(max_length=2000)
    thumbnail_url = models.URLField(max_length=2000, blank=True)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)

    title = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    taken_at = models.DateTimeField(null=True, blank=True)
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    # History research: old photos and maps are often dated only to a year or decade.
    date_precision = models.CharField(max_length=10, choices=DatePrecision.choices, default=DatePrecision.DAY)
    people = models.ManyToManyField("Person", related_name="photos", blank=True)
    place = models.CharField(max_length=255, blank=True)
    source = models.TextField(blank=True)
    # Plain-text transcription of writing in the image, e.g. a letter or map labels.
    transcription = models.TextField(blank=True)
    credit = models.CharField(max_length=255, blank=True)

    stage = models.CharField(max_length=10, choices=Stage.choices, blank=True)
    # Links a "before" photo to the "after" photo of the same spot.
    pair = models.OneToOneField("self", on_delete=models.SET_NULL, related_name="paired_with", null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-taken_at", "-created_at"]

    def __str__(self):
        return self.title or self.url
