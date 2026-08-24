from django.urls import include, path
from rest_framework.routers import DefaultRouter

from verso.views import (
    BookingRequestViewSet,
    BookingViewSet,
    CheckOutViewSet,
    ExpenseViewSet,
    HouseViewSet,
    VentureTaskViewSet,
    VentureViewSet,
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

urlpatterns = [
    path('', include(router.urls)),
]
