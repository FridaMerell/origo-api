from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from accounts.models import CodexToken
from flux.models import Project, Task

User = get_user_model()


class CodexProjectPlanTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='codex-user', password='x')
        _token, self.plaintext = CodexToken.issue(self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'codex {self.plaintext}')

    def test_requires_a_codex_token(self):
        client = APIClient()

        response = client.get('/api/flux/codex/projects/')

        self.assertEqual(response.status_code, 401)

    def test_create_project_plan(self):
        payload = {
            'name': 'Launch plan',
            'milestones': [{'ref': 'm1', 'title': 'Beta'}],
            'tasks': [{'ref': 't1', 'title': 'Write docs', 'milestone_ref': 'm1'}],
        }

        response = self.client.post('/api/flux/codex/projects/', payload, format='json')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['name'], 'Launch plan')
        self.assertEqual(len(response.data['tasks']), 1)
        project = Project.objects.get(pk=response.data['id'])
        self.assertEqual(list(project.members.all()), [self.user])

    def test_created_project_is_private_to_the_token_owner(self):
        self.client.post('/api/flux/codex/projects/', {'name': 'Private plan'}, format='json')

        listing = self.client.get('/api/flux/codex/projects/')

        self.assertEqual(len(listing.data), 1)
        self.assertEqual(listing.data[0]['name'], 'Private plan')

    def test_a_shared_project_is_not_listed_as_private(self):
        other = User.objects.create_user(username='colleague', password='x')
        project = Project.objects.create(name='Shared')
        project.members.add(self.user, other)

        listing = self.client.get('/api/flux/codex/projects/')

        self.assertEqual(listing.data, [])

    def test_get_project_detail(self):
        created = self.client.post('/api/flux/codex/projects/', {'name': 'Plan'}, format='json').data

        response = self.client.get(f'/api/flux/codex/projects/{created["id"]}/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['name'], 'Plan')

    def test_cannot_read_someone_elses_project(self):
        other = User.objects.create_user(username='colleague', password='x')
        project = Project.objects.create(name='Not yours')
        project.members.add(other)

        response = self.client.get(f'/api/flux/codex/projects/{project.pk}/')

        self.assertEqual(response.status_code, 404)

    def test_append_plan_adds_to_the_existing_project(self):
        created = self.client.post('/api/flux/codex/projects/', {'name': 'Plan'}, format='json').data

        response = self.client.post(
            f'/api/flux/codex/projects/{created["id"]}/plan/',
            {'tasks': [{'ref': 't1', 'title': 'New task'}]},
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.data['tasks']), 1)

    def test_add_task_to_existing_project(self):
        created = self.client.post('/api/flux/codex/projects/', {'name': 'Plan'}, format='json').data

        response = self.client.post(
            f'/api/flux/codex/projects/{created["id"]}/tasks/',
            {'title': 'Standalone task'},
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['title'], 'Standalone task')
        self.assertTrue(Task.objects.filter(project_id=created['id'], title='Standalone task').exists())

    def test_add_task_rejects_a_milestone_from_another_project(self):
        created = self.client.post('/api/flux/codex/projects/', {'name': 'Plan'}, format='json').data
        other = self.client.post('/api/flux/codex/projects/', {'name': 'Other plan'}, format='json').data
        other_milestone = self.client.post(
            f'/api/flux/codex/projects/{other["id"]}/plan/',
            {'milestones': [{'ref': 'm1', 'title': 'Elsewhere'}]},
            format='json',
        ).data['milestones'][0]

        response = self.client.post(
            f'/api/flux/codex/projects/{created["id"]}/tasks/',
            {'title': 'Task', 'milestone_id': other_milestone['id']},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
