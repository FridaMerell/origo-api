from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from flux.models import Milestone, Project, Tag

User = get_user_model()


class MilestoneViewSetTests(APITestCase):
    def setUp(self):
        self.member = User.objects.create_user(username='member', password='x')
        self.outsider = User.objects.create_user(username='outsider', password='x')
        self.project = Project.objects.create(name='Origo')
        self.project.members.add(self.member)
        self.client = APIClient()
        self.client.force_authenticate(user=self.member)

    def test_member_can_create_a_milestone(self):
        response = self.client.post('/api/flux/milestones/', {'project': self.project.pk, 'title': 'Launch'})

        self.assertEqual(response.status_code, 201)

    def test_non_member_cannot_create_a_milestone(self):
        client = APIClient()
        client.force_authenticate(user=self.outsider)

        response = client.post('/api/flux/milestones/', {'project': self.project.pk, 'title': 'Launch'})

        self.assertEqual(response.status_code, 400)

    def test_tag_must_be_available_in_the_project(self):
        someone_elses_tag = Tag.objects.create(name='urgent', created_by=self.outsider)

        response = self.client.post(
            '/api/flux/milestones/',
            {'project': self.project.pk, 'title': 'Launch', 'tags': [someone_elses_tag.pk]},
        )

        self.assertEqual(response.status_code, 400)

    def test_own_tag_can_be_attached(self):
        own_tag = Tag.objects.create(name='urgent', created_by=self.member)

        response = self.client.post(
            '/api/flux/milestones/',
            {'project': self.project.pk, 'title': 'Launch', 'tags': [own_tag.pk]},
        )

        self.assertEqual(response.status_code, 201)

    def test_outsider_cannot_see_the_milestone(self):
        Milestone.objects.create(project=self.project, title='Launch')
        client = APIClient()
        client.force_authenticate(user=self.outsider)

        response = client.get('/api/flux/milestones/')

        self.assertEqual(response.data, [])
