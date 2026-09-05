"""Expense views."""
import django.db.models as models
from django.db.models import Q
from django.utils import timezone
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from verso.models import Expense, House
from verso.serializers import ExpenseSerializer


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
        house = House.objects.filter(members=request.user).filter(pk=house_id).first()
        if house is None:
            return Response({'error': 'House not found.'}, status=404)
        expenses = self.get_queryset().filter(
            Q(house=house) | Q(venture__house=house),
            date_incurred__year=year,
        )
        total_expenses = expenses.aggregate(total=models.Sum('amount'))['total'] or 0
        return Response({'year': year, 'total_expenses': total_expenses})
