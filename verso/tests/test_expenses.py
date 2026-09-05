from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from verso.models import Expense, House, Venture

User = get_user_model()


class ExpenseViewSetTests(APITestCase):
    def setUp(self):
        self.member = User.objects.create_user(username='member', password='x')
        self.outsider = User.objects.create_user(username='outsider', password='x')
        self.house = House.objects.create(name='Home')
        self.house.members.add(self.member)
        self.client = APIClient()
        self.client.force_authenticate(user=self.member)

    def test_member_can_create_a_house_expense(self):
        response = self.client.post(
            '/api/verso/expenses/', {'house': self.house.pk, 'amount': '99.50', 'date_incurred': '2026-01-01'}
        )

        self.assertEqual(response.status_code, 201)

    def test_expense_must_belong_to_a_house_or_venture(self):
        response = self.client.post('/api/verso/expenses/', {'amount': '99.50', 'date_incurred': '2026-01-01'})

        self.assertEqual(response.status_code, 400)

    def test_venture_must_belong_to_the_selected_house(self):
        other_house = House.objects.create(name='Other')
        other_house.members.add(self.member)
        venture = Venture.objects.create(name='Renovate', house=other_house)

        response = self.client.post(
            '/api/verso/expenses/',
            {'house': self.house.pk, 'venture': venture.pk, 'amount': '10', 'date_incurred': '2026-01-01'},
        )

        self.assertEqual(response.status_code, 400)

    def test_outsider_cannot_see_the_expense(self):
        Expense.objects.create(house=self.house, amount='10', date_incurred='2026-01-01')
        client = APIClient()
        client.force_authenticate(user=self.outsider)

        response = client.get('/api/verso/expenses/')

        self.assertEqual(response.data, [])

    def test_year_expenses_requires_house_id(self):
        response = self.client.get('/api/verso/expenses/year_expenses/')

        self.assertEqual(response.status_code, 400)

    def test_year_expenses_totals_the_selected_year(self):
        Expense.objects.create(house=self.house, amount='100', date_incurred='2026-01-15')
        Expense.objects.create(house=self.house, amount='50', date_incurred='2026-06-01')
        Expense.objects.create(house=self.house, amount='999', date_incurred='2025-12-31')

        response = self.client.get(
            '/api/verso/expenses/year_expenses/', {'house_id': self.house.pk, 'year': 2026}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['year'], 2026)
        self.assertEqual(str(response.data['total_expenses']), '150.00')

    def test_year_expenses_rejects_a_house_the_user_is_not_a_member_of(self):
        other_house = House.objects.create(name='Other')

        response = self.client.get('/api/verso/expenses/year_expenses/', {'house_id': other_house.pk})

        self.assertEqual(response.status_code, 404)
