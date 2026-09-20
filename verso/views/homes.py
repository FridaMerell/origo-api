"""House views, including the aggregate house dashboard."""
import datetime

import django.db.models as models
from django.db.models import Count, OuterRef, Q, Subquery, Sum
from django.utils import timezone
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from verso.models import Booking, BookingRequest, CheckOut, Expense, HistoryEvent, House, Person, Photo, Venture, VentureTask, VersoUpdate
from verso.serializers import (
    BookingRequestSerializer,
    BookingSerializer,
    CheckOutSerializer,
    ExpenseSerializer,
    HistoryEventSerializer,
    HouseSerializer,
    PersonSerializer,
    PhotoSerializer,
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
    def on_this_day(self, request):
        """History events and photos from earlier years on this calendar day.
        Only items dated to the exact day (``date_precision`` of ``day``) match."""
        try:
            house = self.get_queryset().filter(pk=int(request.query_params.get('house', ''))).first()
        except ValueError:
            return Response({'error': 'A valid house parameter is required.'}, status=400)
        if house is None:
            return Response({'error': 'House not found.'}, status=404)

        day = timezone.localdate()
        if 'date' in request.query_params:
            try:
                day = datetime.date.fromisoformat(request.query_params['date'])
            except ValueError:
                return Response({'error': 'Invalid date parameter, use YYYY-MM-DD.'}, status=400)

        events = HistoryEvent.objects.filter(
            house=house, date_precision='day',
            date_start__month=day.month, date_start__day=day.day, date_start__year__lt=day.year,
        ).prefetch_related('people', 'photos').order_by('-date_start')
        photos = Photo.objects.filter(
            house=house, date_precision='day',
            taken_at__month=day.month, taken_at__day=day.day, taken_at__year__lt=day.year,
        ).prefetch_related('albums', 'tags', 'people').order_by('-taken_at')

        births = Person.objects.filter(
            house=house, birth_date_precision='day',
            birth_date__month=day.month, birth_date__day=day.day, birth_date__year__lt=day.year,
        ).order_by('birth_date')
        deaths = Person.objects.filter(
            house=house, death_date_precision='day',
            death_date__month=day.month, death_date__day=day.day, death_date__year__lt=day.year,
        ).order_by('death_date')

        context = {'request': request}
        birth_data = PersonSerializer(births, many=True, context=context).data
        death_data = PersonSerializer(deaths, many=True, context=context).data
        for item, person in zip(birth_data, births):
            item['years_ago'] = day.year - person.birth_date.year
        for item, person in zip(death_data, deaths):
            item['years_ago'] = day.year - person.death_date.year
        event_data = HistoryEventSerializer(events, many=True, context=context).data
        photo_data = PhotoSerializer(photos, many=True, context=context).data
        for item, event in zip(event_data, events):
            item['years_ago'] = day.year - event.date_start.year
        for item, photo in zip(photo_data, photos):
            item['years_ago'] = day.year - photo.taken_at.year
        return Response({'date': day.isoformat(), 'events': event_data, 'photos': photo_data,
                         'births': birth_data, 'deaths': death_data})

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
