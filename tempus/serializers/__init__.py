"""Tempus' request/response serializers, grouped by feature area.

The re-exports preserve the established ``tempus.serializers`` import path
for views and tests.
"""

from .birdnet import BirdnetDetectionSerializer, BirdnetDeviceSerializer, BirdnetMatchedSpeciesSerializer
from .checklists import (
    ChecklistItemSerializer,
    ChecklistRegisterItemSerializer,
    ChecklistSerializer,
    ObservationSerializer,
)
from .geography import GeoAreaSerializer
from .reference import PhenophaseSerializer, SourceSerializer
from .routes import (
    RouteSerializer,
    RouteStopSerializer,
    RouteSuggestionRunSerializer,
    SuggestedStopsQuerySerializer,
)
from .species import (
    GeneratePhenogramsSerializer,
    PhenogramQuerySerializer,
    PhenogramSerializer,
    RegisterSpeciesSerializer,
    SeasonalOverviewQuerySerializer,
    SeasonalOverviewSerializer,
    SpeciesCategoryListSerializer,
    SpeciesCategoryMembershipSerializer,
    SpeciesCategorySerializer,
    SpeciesChecklistImportSerializer,
    SpeciesFollowSerializer,
    SpeciesReferenceField,
    SpeciesResolveRequestSerializer,
    SpeciesResyncSerializer,
    SpeciesSearchSerializer,
    SpeciesSerializer,
)

__all__ = [
    "BirdnetDetectionSerializer",
    "BirdnetDeviceSerializer",
    "BirdnetMatchedSpeciesSerializer",
    "ChecklistItemSerializer",
    "ChecklistRegisterItemSerializer",
    "ChecklistSerializer",
    "GeneratePhenogramsSerializer",
    "GeoAreaSerializer",
    "ObservationSerializer",
    "PhenogramQuerySerializer",
    "PhenogramSerializer",
    "PhenophaseSerializer",
    "RegisterSpeciesSerializer",
    "RouteSerializer",
    "RouteStopSerializer",
    "RouteSuggestionRunSerializer",
    "SeasonalOverviewQuerySerializer",
    "SeasonalOverviewSerializer",
    "SourceSerializer",
    "SpeciesCategoryListSerializer",
    "SpeciesCategoryMembershipSerializer",
    "SpeciesCategorySerializer",
    "SpeciesChecklistImportSerializer",
    "SpeciesFollowSerializer",
    "SpeciesReferenceField",
    "SpeciesResolveRequestSerializer",
    "SpeciesResyncSerializer",
    "SpeciesSearchSerializer",
    "SpeciesSerializer",
    "SuggestedStopsQuerySerializer",
]
