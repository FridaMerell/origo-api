"""House views, including the aggregate house dashboard."""
import django.db.models as models
from django.db.models import Count, OuterRef, Q, Subquery, Sum
from django.utils import timezone
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from verso.models import Booking, BookingRequest, CheckOut, Expense, House, Venture, VentureTask, VersoUpdate
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
