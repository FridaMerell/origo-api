import django_filters
from django.utils import timezone
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
import django.db.models as models
from django.db.models import Count, OuterRef, Q, Subquery, Sum
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

    @action(detail=False, methods=['get'])
    def dashboard(self, request):
        houses = self.get_queryset()
        house_id = request.query_params.get('house')

        if house_id:
            try:
                house_id = int(house_id)
            except ValueError:
                return Response({'error': 'Invalid house parameter.'}, status=400)
            house = houses.filter(pk=house_id).first()
            if house is None:
                return Response({'error': 'House not found.'}, status=404)
        else:
            house = houses.order_by('pk').first()
            if house is None:
                return Response({'error': 'No houses found.'}, status=404)

        year = timezone.now().year
        if 'year' in request.query_params:
            try:
                year = int(request.query_params['year'])
            except ValueError:
                return Response({'error': 'Invalid year parameter.'}, status=400)

        bookings = Booking.objects.filter(house=house).order_by('start_date')
        booking_requests = BookingRequest.objects.filter(house=house)
        check_outs = CheckOut.objects.filter(booking__house=house)
        venture_expense_total = Expense.objects.filter(
            venture=OuterRef('pk')
        ).order_by().values('venture').annotate(
            total=Sum('amount')
        ).values('total')[:1]
        ventures = Venture.objects.filter(house=house).annotate(
            finished_tasks_count=Count(
                'tasks', filter=Q(tasks__completed=True), distinct=True
            ),
            total_tasks_count=Count('tasks', distinct=True),
            total_spent=Subquery(
                venture_expense_total,
                output_field=models.DecimalField(max_digits=10, decimal_places=2),
            ),
        )
        venture_tasks = VentureTask.objects.filter(venture__house=house)
        expenses = Expense.objects.filter(
            Q(house=house) | Q(venture__house=house)
        ).order_by('-date_incurred')
        updates = VersoUpdate.objects.filter(
            Q(house=house)
            | Q(venture__house=house)
            | Q(task__venture__house=house)
        ).distinct().order_by('-created_at')
        yearly_expense_total = expenses.filter(
            date_incurred__year=year
        ).aggregate(total=Sum('amount'))['total'] or 0

        serializer_context = {'request': request}
        return Response({
            'house': HouseSerializer(house, context=serializer_context).data,
            'houses': HouseSerializer(houses, many=True, context=serializer_context).data,
            'bookings': BookingSerializer(bookings, many=True, context=serializer_context).data,
            'booking_requests': BookingRequestSerializer(
                booking_requests, many=True, context=serializer_context
            ).data,
            'check_outs': CheckOutSerializer(
                check_outs, many=True, context=serializer_context
            ).data,
            'ventures': VentureSerializer(ventures, many=True, context=serializer_context).data,
            'venture_tasks': VentureTaskSerializer(
                venture_tasks, many=True, context=serializer_context
            ).data,
            'expenses': ExpenseSerializer(expenses, many=True, context=serializer_context).data,
            'updates': VersoUpdateSerializer(updates, many=True, context=serializer_context).data,
            'yearly_expense_total': yearly_expense_total,
        })


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
        queryset = CheckOut.objects.filter(
            booking__house__members=self.request.user
        ).distinct()
        house_id = self.request.query_params.get('booking__house')
        if self.action == 'list' and house_id:
            queryset = queryset.filter(booking__house_id=house_id)
        return queryset


class VentureViewSet(viewsets.ModelViewSet):
    serializer_class = VentureSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['house']

    def get_queryset(self):
        return Venture.objects.filter(
            house__members=self.request.user,
        ).distinct()


class VentureTaskViewSet(viewsets.ModelViewSet):
    serializer_class = VentureTaskSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['venture', 'completed']

    def get_queryset(self):
        queryset = VentureTask.objects.filter(
            venture__house__members=self.request.user,
        ).distinct()
        house_id = self.request.query_params.get('venture__house')
        if self.action == 'list' and house_id:
            queryset = queryset.filter(venture__house_id=house_id)
        return queryset


class ExpenseViewSet(viewsets.ModelViewSet):
    serializer_class = ExpenseSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['venture', 'house']

    def get_queryset(self):
        return Expense.objects.filter(
            Q(house__members=self.request.user)
            | Q(venture__house__members=self.request.user)
        ).distinct().order_by('-date_incurred')

    @action(detail=False, methods=['get'])
    def year_expenses(self, request):
        house_id = request.query_params.get('house_id')
        if not house_id:
            return Response({'error': 'house_id query parameter is required.'}, status=400)
        year = timezone.now().year
        if 'year' in request.query_params:
            try:
                year = int(request.query_params['year'])
            except ValueError:
                return Response({'error': 'Invalid year parameter.'}, status=400)
        current_year = year
        house = House.objects.filter(members=request.user).filter(pk=house_id).first()
        if house is None:
            return Response({'error': 'House not found.'}, status=404)
        expenses = self.get_queryset().filter(
            Q(house=house) | Q(venture__house=house),
            date_incurred__year=current_year,
        )
        total_expenses = expenses.aggregate(total=models.Sum('amount'))['total'] or 0
        return Response({'year': current_year, 'total_expenses': total_expenses})


class UpdateViewSet(viewsets.ModelViewSet):
    serializer_class = VersoUpdateSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['venture', 'task', 'author']

    def get_queryset(self):
        queryset = VersoUpdate.objects.filter(
            Q(house__members=self.request.user)
            | Q(venture__house__members=self.request.user)
            | Q(task__venture__house__members=self.request.user)
        ).distinct().order_by('-created_at')
        house_id = self.request.query_params.get('house')
        if self.action == 'list' and house_id:
            queryset = queryset.filter(
                Q(house_id=house_id)
                | Q(venture__house_id=house_id)
                | Q(task__venture__house_id=house_id)
            )
        return queryset

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)
