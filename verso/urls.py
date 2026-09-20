from django.urls import include, path
from rest_framework.routers import DefaultRouter

from verso.views import (
    AlbumViewSet,
    DocumentViewSet,
    HistoryEventViewSet,
    PersonRelationViewSet,
    PersonViewSet,
    PhotoViewSet,
    TagViewSet,
    BookingRequestViewSet,
    BookingViewSet,
    CheckOutViewSet,
    DrawingPageViewSet,
    DrawingViewSet,
    ExpenseViewSet,
    HouseViewSet,
    VentureTaskViewSet,
    VentureViewSet,
    UpdateViewSet,
)

app_name = 'verso'

router = DefaultRouter()
router.register('houses', HouseViewSet, basename='house')
router.register('bookings', BookingViewSet, basename='booking')
router.register('booking-requests', BookingRequestViewSet, basename='bookingrequest')
router.register('check-outs', CheckOutViewSet, basename='checkout')
router.register('ventures', VentureViewSet, basename='venture')
router.register('venture-tasks', VentureTaskViewSet, basename='venturetask')
router.register('expenses', ExpenseViewSet, basename='expense')
router.register('updates', UpdateViewSet, basename='update')
router.register('drawings', DrawingViewSet, basename='drawing')
router.register('drawing-pages', DrawingPageViewSet, basename='drawingpage')
router.register('photos', PhotoViewSet, basename='photo')
router.register('albums', AlbumViewSet, basename='album')
router.register('photo-tags', TagViewSet, basename='phototag')
router.register('documents', DocumentViewSet, basename='document')
router.register('people', PersonViewSet, basename='person')
router.register('person-relations', PersonRelationViewSet, basename='personrelation')
router.register('history-events', HistoryEventViewSet, basename='historyevent')
urlpatterns = [
    path('', include(router.urls)),
]
