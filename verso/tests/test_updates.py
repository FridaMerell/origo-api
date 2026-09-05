from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from verso.models import House, Venture, VersoUpdate

User = get_user_model()


class UpdateViewSetTests(APITestCase):
    def setUp(self):
        self.member = User.objects.create_user(username='member', password='x')
        self.outsider = User.objects.create_user(username='outsider', password='x')
        self.house = House.objects.create(name='Home')
        self.house.members.add(self.member)
        self.client = APIClient()
        self.client.force_authenticate(user=self.member)

    def test_member_can_post_a_house_update(self):
        response = self.client.post('/api/verso/updates/', {'house': self.house.pk, 'title': 'News', 'content': 'Hi'})

        self.assertEqual(response.status_code, 201)
        self.assertEqual(VersoUpdate.objects.get().author, self.member)

    def test_update_must_belong_to_a_house_venture_or_task(self):
        response = self.client.post('/api/verso/updates/', {'title': 'News', 'content': 'Hi'})

        self.assertEqual(response.status_code, 400)

    def test_venture_and_house_must_match(self):
        other_house = House.objects.create(name='Other')
        other_house.members.add(self.member)
        venture = Venture.objects.create(name='Renovate', house=other_house)

        response = self.client.post(
            '/api/verso/updates/',
            {'house': self.house.pk, 'venture': venture.pk, 'title': 'News', 'content': 'Hi'},
        )

        self.assertEqual(response.status_code, 400)

    def test_outsider_cannot_see_the_update(self):
        VersoUpdate.objects.create(house=self.house, title='News', content='Hi', author=self.member)
        client = APIClient()
        client.force_authenticate(user=self.outsider)

        response = client.get('/api/verso/updates/')

        self.assertEqual(response.data, [])

    def test_house_query_param_scopes_the_list(self):
        VersoUpdate.objects.create(house=self.house, title='News', content='Hi', author=self.member)
        other_house = House.objects.create(name='Other')
        other_house.members.add(self.member)
        VersoUpdate.objects.create(house=other_house, title='Other news', content='Hi', author=self.member)

        response = self.client.get('/api/verso/updates/', {'house': self.house.pk})

        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['title'], 'News')
