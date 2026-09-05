from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from flux.models import Document, Milestone, Project

User = get_user_model()


class DocumentViewSetTests(APITestCase):
    def setUp(self):
        self.member = User.objects.create_user(username='member', password='x')
        self.outsider = User.objects.create_user(username='outsider', password='x')
        self.project = Project.objects.create(name='Origo')
        self.project.members.add(self.member)
        self.client = APIClient()
        self.client.force_authenticate(user=self.member)

    def test_member_can_create_a_document(self):
        response = self.client.post(
            '/api/flux/documents/', {'project': self.project.pk, 'title': 'Doc', 'content': 'text'}
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Document.objects.get().author, self.member)

    def test_non_member_cannot_create_a_document(self):
        client = APIClient()
        client.force_authenticate(user=self.outsider)

        response = client.post(
            '/api/flux/documents/', {'project': self.project.pk, 'title': 'Doc', 'content': 'text'}
        )

        self.assertEqual(response.status_code, 400)

    def test_milestone_must_belong_to_the_same_project(self):
        other_project = Project.objects.create(name='Other')
        other_project.members.add(self.member)
        other_milestone = Milestone.objects.create(project=other_project, title='Other launch')

        response = self.client.post(
            '/api/flux/documents/',
            {'project': self.project.pk, 'milestone': other_milestone.pk, 'title': 'Doc', 'content': 'text'},
        )

        self.assertEqual(response.status_code, 400)

    def test_outsider_cannot_see_the_document(self):
        Document.objects.create(project=self.project, title='Doc', content='text')
        client = APIClient()
        client.force_authenticate(user=self.outsider)

        response = client.get('/api/flux/documents/')

        self.assertEqual(response.data, [])
