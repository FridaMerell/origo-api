import django_filters
from django.utils import timezone
from rest_framework import permissions, viewsets

from verso.models import (
    Booking,
    BookingRequest,
    CheckOut,
    Expense,
    VersoUpdate,
    House,
    Venture,
    VentureTask,
    
)
from verso.serializers import (
    BookingRequestSerializer,
    BookingSerializer,
    CheckOutSerializer,
    ExpenseSerializer,
    HouseSerializer,
    VentureSerializer,
    VentureTaskSerializer,
    VersoUpdateSerializer,
)


class HouseViewSet(viewsets.ModelViewSet):
    serializer_class = HouseSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['members']

    def get_queryset(self):
        return House.objects.filter(members=self.request.user).distinct()

    def perform_create(self, serializer):
        house = serializer.save()
        house.members.add(self.request.user)


class BookingFilter(django_filters.FilterSet):
    future = django_filters.BooleanFilter(method='filter_future')

    class Meta:
        model = Booking
        fields = ['house', 'future']

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
        return CheckOut.objects.filter(booking__house__members=self.request.user).distinct()


class VentureViewSet(viewsets.ModelViewSet):
    serializer_class = VentureSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['house']

    def get_queryset(self):
        return Venture.objects.all()


class VentureTaskViewSet(viewsets.ModelViewSet):
    serializer_class = VentureTaskSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['venture', 'completed']

    def get_queryset(self):
        return VentureTask.objects.all()


class ExpenseViewSet(viewsets.ModelViewSet):
    serializer_class = ExpenseSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['venture', 'house']

    def get_queryset(self):
        return Expense.objects.all()

class UpdateViewSet(viewsets.ModelViewSet):
    serializer_class = VersoUpdateSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['venture', 'task', 'author']

    def get_queryset(self):
        return VersoUpdate.objects.all()