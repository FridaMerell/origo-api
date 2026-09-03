from django.urls import include, path
from rest_framework.routers import DefaultRouter

from tempus.api.category_views import SpeciesCategoryViewSet
from tempus.api.reference_views import GeoAreaViewSet, PhenophaseViewSet, SourceViewSet
from tempus.api.views.birdnet import BirdnetDeviceViewSet
from tempus.api.views.checklists import (
    ChecklistItemViewSet,
    ChecklistViewSet,
    ObservationViewSet,
)
from tempus.api.views.routes import RouteStopViewSet, RouteViewSet
from tempus.api.views.species import (
    PhenogramViewSet,
    SpeciesFollowViewSet,
    SpeciesViewSet,
)

app_name = "tempus"

router = DefaultRouter()
router.register("birdnet-devices", BirdnetDeviceViewSet, basename="birdnet-device")
router.register("species", SpeciesViewSet, basename="species")
router.register("species-categories", SpeciesCategoryViewSet, basename="species-category")
router.register("species-follows", SpeciesFollowViewSet, basename="species-follow")
router.register("phenophases", PhenophaseViewSet, basename="phenophase")
router.register("sources", SourceViewSet, basename="source")
router.register("geo-areas", GeoAreaViewSet, basename="geo-area")
router.register("phenograms", PhenogramViewSet, basename="phenogram")
router.register("routes", RouteViewSet, basename="route")
router.register("route-stops", RouteStopViewSet, basename="route-stop")
router.register("checklists", ChecklistViewSet, basename="checklist")
router.register("checklist-items", ChecklistItemViewSet, basename="checklist-item")
router.register("observations", ObservationViewSet, basename="observation")

urlpatterns = [
    path('', include(router.urls)),
]
