"""Tempus' persistence models, grouped by feature area.

The re-exports preserve the established ``tempus.models`` import path for
views, services, the admin site, and migrations.
"""

from .birdnet import BIRDNET_DETECTION_CHANNEL, BirdnetDetection, BirdnetDevice
from .checklists import Checklist, ChecklistItem, Observation
from .geography import GeoArea
from .phenology import Phenogram, PhenogramGeneration
from .reference import Phenophase, Source
from .routes import Route, RouteStop, RouteSuggestionRun
from .species import Species, SpeciesCategory, SpeciesCategoryMembership, SpeciesFollow

__all__ = [
    "BIRDNET_DETECTION_CHANNEL",
    "BirdnetDetection",
    "BirdnetDevice",
    "Checklist",
    "ChecklistItem",
    "GeoArea",
    "Observation",
    "Phenogram",
    "PhenogramGeneration",
    "Phenophase",
    "Route",
    "RouteStop",
    "RouteSuggestionRun",
    "Source",
    "Species",
    "SpeciesCategory",
    "SpeciesCategoryMembership",
    "SpeciesFollow",
]
