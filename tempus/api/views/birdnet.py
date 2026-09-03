"""BirdNET device and detection endpoints."""
from tempus.views import BirdnetDeviceViewSet, BirdnetDetectionIngestView, BirdnetDetectionStreamView

__all__ = [
    "BirdnetDeviceViewSet",
    "BirdnetDetectionIngestView",
    "BirdnetDetectionStreamView",
]
