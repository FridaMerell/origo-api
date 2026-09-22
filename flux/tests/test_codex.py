from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from accounts.models import CodexToken
from flux.models import Entity, Project, Resource, Role, RolePermission, Task

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

    def test_update_document_partially(self):
        created = self.client.post('/api/flux/codex/projects/', {'name': 'Plan'}, format='json').data
        document = self.client.post(
            f'/api/flux/codex/projects/{created["id"]}/plan/',
            {'documents': [{'title': 'Original', 'content': 'v1'}]},
            format='json',
        ).data['documents'][0]

        response = self.client.patch(
            f'/api/flux/codex/projects/{created["id"]}/documents/{document["id"]}/',
            {'content': 'v2'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['content'], 'v2')
        self.assertEqual(response.data['title'], 'Original')

        project = self.client.get(f'/api/flux/codex/projects/{created["id"]}/').data
        self.assertEqual(len(project['documents']), 1)
        self.assertEqual(project['documents'][0]['content'], 'v2')

    def test_update_document_requires_at_least_one_field(self):
        created = self.client.post('/api/flux/codex/projects/', {'name': 'Plan'}, format='json').data
        document = self.client.post(
            f'/api/flux/codex/projects/{created["id"]}/plan/',
            {'documents': [{'title': 'Doc'}]},
            format='json',
        ).data['documents'][0]

        response = self.client.patch(
            f'/api/flux/codex/projects/{created["id"]}/documents/{document["id"]}/',
            {},
            format='json',
        )

        self.assertEqual(response.status_code, 400)

    def test_update_role_replaces_its_permissions(self):
        created = self.client.post('/api/flux/codex/projects/', {'name': 'Plan'}, format='json').data
        project = Project.objects.get(pk=created['id'])
        entity = Entity.objects.create(project=project, name='Work')
        resource = Resource.objects.create(entity=entity, path='works')
        role = Role.objects.create(project=project, name='Reader')
        RolePermission.objects.create(
            role=role,
            resource=resource,
            operation=Resource.Operation.LIST,
            scope=RolePermission.Scope.ALL,
        )

        response = self.client.patch(
            f'/api/flux/codex/projects/{project.id}/roles/{role.id}/',
            {
                'description': 'Can manage shared works.',
                'permissions': [
                    {'resource_id': resource.id, 'operation': 'create', 'scope': 'all'},
                    {'resource_id': resource.id, 'operation': 'update', 'scope': 'all'},
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['name'], 'Reader')
        self.assertEqual(
            response.data['permissions'],
            [
                {'resource_id': resource.id, 'operation': 'create', 'scope': 'all'},
                {'resource_id': resource.id, 'operation': 'update', 'scope': 'all'},
            ],
        )

    def test_resource_update_creates_a_missing_resource(self):
        created = self.client.post('/api/flux/codex/projects/', {'name': 'Plan'}, format='json').data
        project = Project.objects.get(pk=created['id'])
        entity = Entity.objects.create(project=project, name='Edition')

        response = self.client.patch(
            f'/api/flux/codex/projects/{project.id}/entities/{entity.id}/resource/',
            {'path': 'editions', 'operations': ['list', 'retrieve', 'create', 'update', 'delete']},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['path'], 'editions')

    def test_update_document_rejects_a_milestone_from_another_project(self):
        created = self.client.post('/api/flux/codex/projects/', {'name': 'Plan'}, format='json').data
        document = self.client.post(
            f'/api/flux/codex/projects/{created["id"]}/plan/',
            {'documents': [{'title': 'Doc'}]},
            format='json',
        ).data['documents'][0]
        other = self.client.post('/api/flux/codex/projects/', {'name': 'Other plan'}, format='json').data
        other_milestone = self.client.post(
            f'/api/flux/codex/projects/{other["id"]}/plan/',
            {'milestones': [{'ref': 'm1', 'title': 'Elsewhere'}]},
            format='json',
        ).data['milestones'][0]

        response = self.client.patch(
            f'/api/flux/codex/projects/{created["id"]}/documents/{document["id"]}/',
            {'milestone_id': other_milestone['id']},
            format='json',
        )

        self.assertEqual(response.status_code, 400)

    def test_cannot_update_a_document_in_someone_elses_project(self):
        other = User.objects.create_user(username='colleague', password='x')
        project = Project.objects.create(name='Not yours')
        project.members.add(other)

        response = self.client.patch(
            f'/api/flux/codex/projects/{project.pk}/documents/1/',
            {'content': 'nope'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)

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
