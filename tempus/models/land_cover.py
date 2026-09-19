"""Background Lantmäteriet land-cover prefetch tracking.

A ``LandCoverFetch`` is keyed by the padded area geometry actually fetched,
not by its trigger - ``tempus.services.lantmateriet.map_for_area`` (and the
bbox-based fetches it wraps) take a plain GeoJSON geometry and know nothing
about Locale. The optional ``locale`` link only covers the current
auto-prefetch trigger (see tempus/signals.py); a future non-Locale caller can
create rows the same way by leaving it unset.
"""

import uuid

from django.db import models

from .geography import Locale


class LandCoverFetch(models.Model):
    """Latest background land-cover, hydrography, place-name, and building fetch for a padded area.

    ``result`` holds the Marktäcke Direkt land-cover/wetland features,
    ``hydrography`` the Hydrografi lake/watercourse/coastline features,
    ``place_names`` the Ortnamn Direkt place names, and ``buildings`` the
    Byggnad Direkt building features for the same padded geometry - one
    background run populates all four. Replaces earlier results in place,
    like ``RouteSuggestionRun`` for routes.

    ``place_names`` comes from OpenStreetMap
    (``services.openstreetmap.place_names_in_geometry``): one Overpass query
    for the padded area, so it is complete for the area. Lantmäteriet's
    Ortnamn Direkt cannot be queried by area, which is why it is not used
    here (see docs/tempus/lantmateriet-ortnamn.md).
    ``buildings`` (``services.lantmateriet.buildings_in_geometry``) IS an
    exact clip, like land cover/hydrography - Byggnad Direkt accepts an
    arbitrary search geometry, just tiled client-side to respect its
    per-request area/perimeter limit. ``roads`` comes from Trafikverket
    (``services.trafikverket.roads_in_geometry``), a different provider:
    queried by bbox and then clipped to the exact geometry here.
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
    locale = models.OneToOneField(
        Locale,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="land_cover_fetch",
    )
    geometry = models.JSONField(default=dict, blank=True)
    buffer_metres = models.PositiveIntegerField(default=5000)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    result = models.JSONField(default=dict, blank=True)
    hydrography = models.JSONField(default=dict, blank=True)
    place_names = models.JSONField(default=dict, blank=True)
    buildings = models.JSONField(default=dict, blank=True)
    roads = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        target = self.locale or "standalone area"
        return f"{target}: land-cover fetch ({self.status})"
