from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from flux.models import Project, Update

User = get_user_model()


class UpdateViewSetTests(APITestCase):
    def setUp(self):
        self.member = User.objects.create_user(username='member', password='x')
        self.outsider = User.objects.create_user(username='outsider', password='x')
        self.project = Project.objects.create(name='Origo')
        self.project.members.add(self.member)
        self.client = APIClient()
        self.client.force_authenticate(user=self.member)

    def test_member_can_post_an_update(self):
        response = self.client.post('/api/flux/updates/', {'project': self.project.pk, 'content': 'Shipped it'})

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Update.objects.get().author, self.member)

    def test_non_member_cannot_post_an_update(self):
        client = APIClient()
        client.force_authenticate(user=self.outsider)

        response = client.post('/api/flux/updates/', {'project': self.project.pk, 'content': 'Shipped it'})

        self.assertEqual(response.status_code, 400)

    def test_outsider_cannot_see_the_update(self):
        Update.objects.create(project=self.project, content='Shipped it')
        client = APIClient()
        client.force_authenticate(user=self.outsider)

        response = client.get('/api/flux/updates/')

        self.assertEqual(response.data, [])
