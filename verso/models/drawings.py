"""Simple measured drawings for houses and ventures, split into pages."""

from django.conf import settings
from django.db import models

from .homes import House
from .ventures import Venture


class Drawing(models.Model):
    class Unit(models.TextChoices):
        MILLIMETER = "mm", "Millimeter"
        CENTIMETER = "cm", "Centimeter"
        METER = "m", "Meter"

    house = models.ForeignKey(House, on_delete=models.CASCADE, related_name="drawings")
    venture = models.ForeignKey(Venture, on_delete=models.SET_NULL, related_name="drawings", null=True, blank=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    unit = models.CharField(max_length=2, choices=Unit.choices, default=Unit.MILLIMETER)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="verso_drawings")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.name


class DrawingPage(models.Model):
    """One canvas of a drawing, e.g. one facade. ``elements`` holds a list of
    drawing objects (lines, polygons, dimensions, notes...) in the drawing's unit."""

    drawing = models.ForeignKey(Drawing, on_delete=models.CASCADE, related_name="pages")
    name = models.CharField(max_length=255, blank=True)
    order = models.PositiveIntegerField(default=0)
    width = models.DecimalField(max_digits=12, decimal_places=2, default=10000)
    height = models.DecimalField(max_digits=12, decimal_places=2, default=10000)
    elements = models.JSONField(blank=True, default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["drawing", "order", "id"]

    def __str__(self):
        return f"{self.drawing.name} – {self.name or self.order}"
