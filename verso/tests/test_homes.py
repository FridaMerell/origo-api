from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from verso.models import Booking, Expense, House, Venture, VentureTask

User = get_user_model()


class HouseViewSetTests(APITestCase):
    def setUp(self):
        self.member = User.objects.create_user(username='member', password='x')
        self.outsider = User.objects.create_user(username='outsider', password='x')
        self.house = House.objects.create(name='Home')
        self.house.members.add(self.member)
        self.others_house = House.objects.create(name='Someone else')
        self.others_house.members.add(self.outsider)

    def test_list_only_returns_houses_the_user_belongs_to(self):
        client = APIClient()
        client.force_authenticate(user=self.member)

        response = client.get('/api/verso/houses/')

        names = [row['name'] for row in response.data]
        self.assertEqual(names, ['Home'])

    def test_creating_a_house_adds_the_creator_as_a_member(self):
        client = APIClient()
        client.force_authenticate(user=self.member)

        response = client.post('/api/verso/houses/', {'name': 'New place'})

        self.assertEqual(response.status_code, 201)
        house = House.objects.get(pk=response.data['id'])
        self.assertIn(self.member, house.members.all())

    def test_dashboard_requires_at_least_one_house(self):
        client = APIClient()
        client.force_authenticate(user=self.outsider)
        House.objects.filter(pk=self.others_house.pk).delete()

        response = client.get('/api/verso/houses/dashboard/')

        self.assertEqual(response.status_code, 404)

    def test_dashboard_aggregates_data_for_the_selected_house(self):
        Booking.objects.create(house=self.house, visitor='Guest', start_date='2026-01-01', end_date='2026-01-03')
        venture = Venture.objects.create(name='Renovate kitchen', house=self.house)
        VentureTask.objects.create(venture=venture, name='Buy tiles', completed=True)
        Expense.objects.create(house=self.house, amount='150.00', date_incurred='2026-01-02')
        client = APIClient()
        client.force_authenticate(user=self.member)

        response = client.get('/api/verso/houses/dashboard/', {'house': self.house.pk})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['house']['id'], self.house.pk)
        self.assertEqual(len(response.data['bookings']), 1)
        self.assertEqual(len(response.data['ventures']), 1)
        self.assertEqual(response.data['ventures'][0]['finished_tasks_count'], 1)
        self.assertEqual(response.data['ventures'][0]['total_tasks_count'], 1)

    def test_dashboard_rejects_a_house_the_user_is_not_a_member_of(self):
        client = APIClient()
        client.force_authenticate(user=self.member)

        response = client.get('/api/verso/houses/dashboard/', {'house': self.others_house.pk})

        self.assertEqual(response.status_code, 404)
