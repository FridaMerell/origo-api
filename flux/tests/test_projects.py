from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from flux.models import Document, Milestone, Project, Task, Update

User = get_user_model()


class ProjectViewSetTests(APITestCase):
    def setUp(self):
        self.member = User.objects.create_user(username='member', password='x')
        self.outsider = User.objects.create_user(username='outsider', password='x')
        self.project = Project.objects.create(name='Origo')
        self.project.members.add(self.member)
        self.client = APIClient()
        self.client.force_authenticate(user=self.member)

    def test_creating_a_project_adds_the_creator_as_a_member(self):
        response = self.client.post('/api/flux/projects/', {'name': 'New project'})

        self.assertEqual(response.status_code, 201)
        project = Project.objects.get(pk=response.data['id'])
        self.assertIn(self.member, project.members.all())

    def test_outsider_cannot_see_the_project(self):
        client = APIClient()
        client.force_authenticate(user=self.outsider)

        response = client.get('/api/flux/projects/')

        self.assertEqual(response.data, [])

    def test_board_aggregates_related_data(self):
        milestone = Milestone.objects.create(project=self.project, title='Launch')
        task = Task.objects.create(project=self.project, milestone=milestone, title='Ship it')
        Update.objects.create(project=self.project, content='Update')
        Document.objects.create(project=self.project, title='Doc', content='...')

        response = self.client.get(f'/api/flux/projects/{self.project.pk}/board/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['project']['id'], self.project.pk)
        self.assertEqual(len(response.data['milestones']), 1)
        self.assertEqual(len(response.data['tasks']), 1)
        self.assertEqual(len(response.data['updates']), 1)
        self.assertEqual(len(response.data['documents']), 1)
        self.assertIn(str(self.member.pk), [str(row['id']) for row in response.data['users']])

    def test_outsider_cannot_open_the_board(self):
        client = APIClient()
        client.force_authenticate(user=self.outsider)

        response = client.get(f'/api/flux/projects/{self.project.pk}/board/')

        self.assertEqual(response.status_code, 404)
