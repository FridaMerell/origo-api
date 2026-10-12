"""Booking, booking-request, and check-out views."""
import django_filters
from django.utils import timezone
from rest_framework import permissions, viewsets

from verso.models import Booking, BookingRequest, CheckOut
from verso.serializers import BookingRequestSerializer, BookingSerializer, CheckOutSerializer


class BookingFilter(django_filters.FilterSet):
    future = django_filters.BooleanFilter(method='filter_future')
    # Together these select every booking that overlaps the given date range.
    ends_on_or_after = django_filters.DateFilter(field_name='end_date', lookup_expr='gte')
    starts_on_or_before = django_filters.DateFilter(field_name='start_date', lookup_expr='lte')

    class Meta:
        model = Booking
        fields = ['house', 'future', 'ends_on_or_after', 'starts_on_or_before']

    def filter_future(self, queryset, name, value):
        today = timezone.localdate()
        if value:
            return queryset.filter(start_date__gte=today)
        return queryset.filter(start_date__lt=today)


class BookingViewSet(viewsets.ModelViewSet):
    serializer_class = BookingSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_class = BookingFilter

    def get_queryset(self):
        return Booking.objects.filter(house__members=self.request.user).distinct().order_by('start_date')


class BookingRequestViewSet(viewsets.ModelViewSet):
    serializer_class = BookingRequestSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['house', 'status']

    def get_queryset(self):
        return BookingRequest.objects.filter(house__members=self.request.user).distinct()


class CheckOutViewSet(viewsets.ModelViewSet):
    serializer_class = CheckOutSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['booking']

    def get_queryset(self):
        queryset = CheckOut.objects.filter(
            booking__house__members=self.request.user
        ).distinct()
        house_id = self.request.query_params.get('booking__house')
        if self.action == 'list' and house_id:
            queryset = queryset.filter(booking__house_id=house_id)
        return queryset
