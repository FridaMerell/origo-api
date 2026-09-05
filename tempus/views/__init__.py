"""Tempus' viewsets and API views, grouped by feature area.

The re-exports preserve the established ``tempus.views`` import path for
urls, the admin site, and tests.
"""

from .birdnet import (
    BirdnetDetectionIngestView,
    BirdnetDetectionStreamView,
    BirdnetDeviceViewSet,
    ServerSentEventRenderer,
)
from .checklists import (
    ChecklistItemViewSet,
    ChecklistViewSet,
    ObservationFilter,
    ObservationViewSet,
)
from .reference import GeoAreaViewSet, PhenophaseViewSet, SourceViewSet
from .routes import RouteStopViewSet, RouteViewSet
from .species import (
    PhenogramViewSet,
    SpeciesCategoryViewSet,
    SpeciesFilter,
    SpeciesFollowViewSet,
    SpeciesViewSet,
)

__all__ = [
    "BirdnetDetectionIngestView",
    "BirdnetDetectionStreamView",
    "BirdnetDeviceViewSet",
    "ChecklistItemViewSet",
    "ChecklistViewSet",
    "GeoAreaViewSet",
    "ObservationFilter",
    "ObservationViewSet",
    "PhenogramViewSet",
    "PhenophaseViewSet",
    "RouteStopViewSet",
    "RouteViewSet",
    "ServerSentEventRenderer",
    "SourceViewSet",
    "SpeciesCategoryViewSet",
    "SpeciesFilter",
    "SpeciesFollowViewSet",
    "SpeciesViewSet",
]
