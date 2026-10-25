"""Verso views, organised by domain to match ``verso.serializers``."""

from .bookings import BookingFilter, BookingRequestViewSet, BookingViewSet, CheckOutViewSet
from .documents import DocumentViewSet
from .drawings import DrawingPageViewSet, DrawingViewSet
from .expenses import ExpenseViewSet
from .history import HistoryEventViewSet, PersonRelationViewSet, PersonViewSet
from .homes import HouseViewSet
from .incomes import IncomeViewSet
from .photos import AlbumViewSet, PhotoViewSet, TagViewSet
from .residential_heating import ResidentialHeatingViewSet
from .updates import UpdateViewSet
from .ventures import VentureTaskViewSet, VentureViewSet

__all__ = [
    "DocumentViewSet",
    "HistoryEventViewSet",
    "PersonRelationViewSet",
    "PersonViewSet",
    "AlbumViewSet",
    "PhotoViewSet",
    "TagViewSet",
    "BookingFilter",
    "BookingRequestViewSet",
    "BookingViewSet",
    "CheckOutViewSet",
    "DrawingPageViewSet",
    "DrawingViewSet",
    "ExpenseViewSet",
    "HouseViewSet",
    "IncomeViewSet",
    "ResidentialHeatingViewSet",
    "UpdateViewSet",
    "VentureTaskViewSet",
    "VentureViewSet",
]
