from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from verso.models import House, Venture, VentureTask

User = get_user_model()


class VentureViewSetTests(APITestCase):
    def setUp(self):
        self.member = User.objects.create_user(username='member', password='x')
        self.outsider = User.objects.create_user(username='outsider', password='x')
        self.house = House.objects.create(name='Home')
        self.house.members.add(self.member)
        self.client = APIClient()
        self.client.force_authenticate(user=self.member)

    def test_member_can_create_a_venture_for_their_house(self):
        response = self.client.post('/api/verso/ventures/', {'name': 'Renovate kitchen', 'house': self.house.pk})

        self.assertEqual(response.status_code, 201)

    def test_venture_must_belong_to_a_house(self):
        response = self.client.post('/api/verso/ventures/', {'name': 'Renovate kitchen'})

        self.assertEqual(response.status_code, 400)

    def test_non_member_cannot_create_a_venture_for_the_house(self):
        client = APIClient()
        client.force_authenticate(user=self.outsider)

        response = client.post('/api/verso/ventures/', {'name': 'Renovate kitchen', 'house': self.house.pk})

        self.assertEqual(response.status_code, 400)

    def test_outsider_cannot_see_the_venture(self):
        Venture.objects.create(name='Renovate kitchen', house=self.house)
        client = APIClient()
        client.force_authenticate(user=self.outsider)

        response = client.get('/api/verso/ventures/')

        self.assertEqual(response.data, [])


class VentureTaskViewSetTests(APITestCase):
    def setUp(self):
        self.member = User.objects.create_user(username='member', password='x')
        self.outsider = User.objects.create_user(username='outsider', password='x')
        self.house = House.objects.create(name='Home')
        self.house.members.add(self.member)
        self.venture = Venture.objects.create(name='Renovate kitchen', house=self.house)
        self.client = APIClient()
        self.client.force_authenticate(user=self.member)

    def test_member_can_create_a_task_for_the_venture(self):
        response = self.client.post('/api/verso/venture-tasks/', {'venture': self.venture.pk, 'name': 'Buy tiles'})

        self.assertEqual(response.status_code, 201)

    def test_non_member_cannot_create_a_task_for_the_venture(self):
        client = APIClient()
        client.force_authenticate(user=self.outsider)

        response = client.post('/api/verso/venture-tasks/', {'venture': self.venture.pk, 'name': 'Buy tiles'})

        self.assertEqual(response.status_code, 400)

    def test_house_query_param_scopes_the_list(self):
        VentureTask.objects.create(venture=self.venture, name='Buy tiles')
        other_house = House.objects.create(name='Other')
        other_house.members.add(self.member)
        other_venture = Venture.objects.create(name='Other venture', house=other_house)
        VentureTask.objects.create(venture=other_venture, name='Other task')

        response = self.client.get('/api/verso/venture-tasks/', {'venture__house': self.house.pk})

        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['name'], 'Buy tiles')
