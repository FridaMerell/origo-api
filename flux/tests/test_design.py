from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from accounts.models import CodexToken
from flux.models import (
    Document,
    Entity,
    Field,
    Milestone,
    Project,
    Relation,
    Resource,
    Role,
    Screen,
    Task,
)

User = get_user_model()


class DesignApiTests(APITestCase):
    def setUp(self):
        self.member = User.objects.create_user(username='member', password='x')
        self.outsider = User.objects.create_user(username='outsider', password='x')
        self.project = Project.objects.create(name='Book Club')
        self.project.members.add(self.member)
        self.other_project = Project.objects.create(name='Other')
        self.other_project.members.add(self.member)
        self.client = APIClient()
        self.client.force_authenticate(user=self.member)
        self.author = Entity.objects.create(project=self.project, name='Author')
        self.book = Entity.objects.create(project=self.project, name='Book')
        Field.objects.create(entity=self.book, name='title')
        self.foreign = Entity.objects.create(project=self.other_project, name='Foreign')

    def test_member_can_create_an_entity(self):
        response = self.client.post('/api/flux/entities/', {'project': self.project.pk, 'name': 'Genre'})

        self.assertEqual(response.status_code, 201)

    def test_non_member_cannot_create_an_entity(self):
        client = APIClient()
        client.force_authenticate(user=self.outsider)

        response = client.post('/api/flux/entities/', {'project': self.project.pk, 'name': 'Genre'})

        self.assertEqual(response.status_code, 400)

    def test_non_member_does_not_see_entities(self):
        client = APIClient()
        client.force_authenticate(user=self.outsider)

        self.assertEqual(client.get('/api/flux/entities/').data, [])

    def test_field_requires_project_membership(self):
        client = APIClient()
        client.force_authenticate(user=self.outsider)

        response = client.post('/api/flux/fields/', {'entity': self.book.pk, 'name': 'isbn'})

        self.assertEqual(response.status_code, 400)

    def test_relation_target_must_be_in_the_same_project(self):
        response = self.client.post(
            '/api/flux/relations/',
            {'source': self.book.pk, 'target': self.foreign.pk, 'name': 'foreign'},
        )

        self.assertEqual(response.status_code, 400)

    def test_relation_within_a_project_is_created(self):
        response = self.client.post(
            '/api/flux/relations/',
            {'source': self.book.pk, 'target': self.author.pk, 'name': 'author', 'kind': 'fk'},
        )

        self.assertEqual(response.status_code, 201)

    def test_stack_profile_rejects_unknown_targets(self):
        response = self.client.post(
            '/api/flux/stack-profiles/', {'project': self.project.pk, 'targets': ['cobol']}, format='json'
        )

        self.assertEqual(response.status_code, 400)

    def test_stack_profile_accepts_known_targets(self):
        response = self.client.post(
            '/api/flux/stack-profiles/', {'project': self.project.pk, 'targets': ['django', 'csharp']}, format='json'
        )

        self.assertEqual(response.status_code, 201)

    def test_resource_rejects_unknown_operations(self):
        response = self.client.post(
            '/api/flux/resources/',
            {'entity': self.book.pk, 'path': 'books', 'operations': ['explode']},
            format='json',
        )

        self.assertEqual(response.status_code, 400)

    def test_role_permission_resource_must_be_in_the_roles_project(self):
        role = Role.objects.create(project=self.project, name='reader')
        foreign_resource = Resource.objects.create(entity=self.foreign, path='foreign', operations=['list'])

        response = self.client.post(
            '/api/flux/role-permissions/',
            {'role': role.pk, 'resource': foreign_resource.pk, 'operation': 'list'},
        )

        self.assertEqual(response.status_code, 400)

    def test_screen_parent_must_be_in_the_same_project(self):
        foreign_screen = Screen.objects.create(project=self.other_project, name='Home', route='/')

        response = self.client.post(
            '/api/flux/screens/',
            {'project': self.project.pk, 'name': 'Books', 'route': '/books', 'parent': foreign_screen.pk},
        )

        self.assertEqual(response.status_code, 400)

    def test_screen_entities_must_be_in_the_same_project(self):
        response = self.client.post(
            '/api/flux/screens/',
            {'project': self.project.pk, 'name': 'Books', 'route': '/books', 'entities': [self.foreign.pk]},
            format='json',
        )

        self.assertEqual(response.status_code, 400)

    def test_relation_name_cannot_clash_with_a_field(self):
        response = self.client.post(
            '/api/flux/relations/',
            {'source': self.book.pk, 'target': self.author.pk, 'name': 'title'},
        )

        self.assertEqual(response.status_code, 400)

    def test_field_name_cannot_clash_with_a_relation(self):
        Relation.objects.create(source=self.book, target=self.author, name='author')

        response = self.client.post('/api/flux/fields/', {'entity': self.book.pk, 'name': 'author'})

        self.assertEqual(response.status_code, 400)

    def test_seed_row_rejects_unknown_keys(self):
        response = self.client.post(
            '/api/flux/seed-rows/', {'entity': self.book.pk, 'data': {'title': 'Dune', 'colour': 'red'}}, format='json'
        )

        self.assertEqual(response.status_code, 400)

    def test_seed_row_accepts_fields_relations_and_id(self):
        Relation.objects.create(source=self.book, target=self.author, name='author')

        response = self.client.post(
            '/api/flux/seed-rows/',
            {'entity': self.book.pk, 'data': {'id': 1, 'title': 'Dune', 'author': 1}},
            format='json',
        )

        self.assertEqual(response.status_code, 201)

    def test_generate_tasks_tolerates_duplicate_milestone_and_task_titles(self):
        milestone = Milestone.objects.create(project=self.project, title='Datamodell')
        Milestone.objects.create(project=self.project, title='Datamodell')
        Task.objects.create(project=self.project, milestone=milestone, title='Modell: Book')
        Task.objects.create(project=self.project, milestone=milestone, title='Modell: Book')

        response = self.client.post(f'/api/flux/projects/{self.project.pk}/generate-tasks/')

        self.assertEqual(response.status_code, 201)
        titles = {item['title'] for item in response.data['created']}
        self.assertNotIn('Modell: Book', titles)
        self.assertIn('Modell: Author', titles)

    def test_scaffold_document_tolerates_duplicate_titles(self):
        Document.objects.create(project=self.project, title='Scaffold: django')
        Document.objects.create(project=self.project, title='Scaffold: django')

        response = self.client.post(
            f'/api/flux/projects/{self.project.pk}/scaffold-document/', {'target': 'django'}, format='json'
        )

        self.assertEqual(response.status_code, 200)

    def test_seed_row_data_must_be_an_object(self):
        response = self.client.post(
            '/api/flux/seed-rows/', {'entity': self.author.pk, 'data': ['not', 'an', 'object']}, format='json'
        )

        self.assertEqual(response.status_code, 400)

    def test_scaffold_returns_files_for_a_target(self):
        response = self.client.get(f'/api/flux/projects/{self.project.pk}/scaffold/?target=django')

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['path'] for item in response.data['files']], ['book_club/models.py'])
        self.assertIn('class Book(models.Model):', response.data['files'][0]['content'])

    def test_scaffold_rejects_an_unknown_target(self):
        response = self.client.get(f'/api/flux/projects/{self.project.pk}/scaffold/?target=rust')

        self.assertEqual(response.status_code, 400)

    def test_scaffold_is_not_available_to_non_members(self):
        client = APIClient()
        client.force_authenticate(user=self.outsider)

        response = client.get(f'/api/flux/projects/{self.project.pk}/scaffold/?target=django')

        self.assertEqual(response.status_code, 404)

    def test_scaffold_document_is_updated_in_place(self):
        url = f'/api/flux/projects/{self.project.pk}/scaffold-document/'

        first = self.client.post(url, {'target': 'django'}, format='json')
        second = self.client.post(url, {'target': 'django'}, format='json')

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(Document.objects.filter(project=self.project, title='Scaffold: django').count(), 1)

    def test_generate_tasks_creates_standard_tasks_once(self):
        Resource.objects.create(entity=self.book, path='books', operations=['list'])
        url = f'/api/flux/projects/{self.project.pk}/generate-tasks/'

        first = self.client.post(url)
        second = self.client.post(url)

        self.assertEqual(first.status_code, 201)
        titles = {item['title'] for item in first.data['created']}
        self.assertIn('Modell: Book', titles)
        self.assertIn('API: books', titles)
        self.assertIn('Tester: Book', titles)
        self.assertEqual(second.data['created'], [])
        self.assertEqual(Task.objects.filter(project=self.project, title='Modell: Book').count(), 1)
        self.assertTrue(Milestone.objects.filter(project=self.project, title='Datamodell').exists())


class CodexDesignTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='codex-user', password='x')
        _token, plaintext = CodexToken.issue(self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'codex {plaintext}')
        self.payload = {
            'name': 'Book club',
            'stack_profile': {'targets': ['django'], 'app_label': 'books'},
            'entities': [
                {'ref': 'author', 'name': 'Author', 'fields': [{'name': 'name', 'type': 'string'}]},
                {'ref': 'book', 'name': 'Book', 'fields': [{'name': 'title'}]},
            ],
            'relations': [{'source_ref': 'book', 'target_ref': 'author', 'name': 'author', 'related_name': 'books'}],
            'resources': [{'entity_ref': 'book', 'path': 'books', 'operations': ['list', 'retrieve']}],
            'roles': [{'name': 'reader', 'permissions': [{'resource_ref': 'book', 'operation': 'list'}]}],
            'screens': [
                {'ref': 's1', 'name': 'Books', 'route': '/books', 'entity_refs': ['book']},
                {'ref': 's2', 'name': 'Detail', 'route': '/books/[id]', 'parent_ref': 's1'},
            ],
            'integrations': [{'name': 'Stripe', 'kind': 'payment', 'env_vars': ['STRIPE_KEY']}],
            'seeds': [{'entity_ref': 'author', 'rows': [{'name': 'Le Guin'}]}],
        }

    def create_project(self):
        return self.client.post('/api/flux/codex/projects/', self.payload, format='json')

    def test_import_creates_the_whole_design(self):
        response = self.create_project()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.data['entities']), 2)
        self.assertEqual(len(response.data['relations']), 1)
        self.assertEqual(response.data['stack_profile']['app_label'], 'books')
        self.assertEqual(len(response.data['resources']), 1)
        self.assertEqual(response.data['roles'][0]['permissions'][0]['operation'], 'list')
        self.assertEqual(len(response.data['screens']), 2)
        self.assertEqual(response.data['integrations'][0]['env_vars'], ['STRIPE_KEY'])
        self.assertEqual(len(response.data['seeds']), 1)

    def test_import_rejects_a_relation_to_an_unknown_entity(self):
        self.payload['relations'][0]['target_ref'] = 'nope'

        self.assertEqual(self.create_project().status_code, 400)

    def test_import_rejects_an_invalid_field_type(self):
        self.payload['entities'][0]['fields'][0]['type'] = 'blob'

        self.assertEqual(self.create_project().status_code, 400)

    def test_import_rolls_back_when_the_design_is_invalid(self):
        self.payload['resources'][0]['entity_ref'] = 'nope'

        self.create_project()

        self.assertFalse(Project.objects.filter(name='Book club').exists())

    def test_permission_needs_a_resource_on_the_entity(self):
        self.payload['roles'][0]['permissions'][0]['resource_ref'] = 'author'

        self.assertEqual(self.create_project().status_code, 400)

    def test_import_rejects_duplicate_roles_permissions_routes_and_integrations(self):
        cases = [
            ('roles', {'name': 'reader'}),
            ('screens', {'ref': 's3', 'name': 'Again', 'route': '/books'}),
            ('integrations', {'name': 'Stripe'}),
        ]
        for key, duplicate in cases:
            with self.subTest(key=key):
                payload = {**self.payload, key: [*self.payload[key], duplicate]}
                response = self.client.post('/api/flux/codex/projects/', payload, format='json')
                self.assertEqual(response.status_code, 400)

    def test_import_rejects_the_same_permission_twice(self):
        permission = {'resource_ref': 'book', 'operation': 'list'}
        self.payload['roles'][0]['permissions'] = [permission, permission]

        self.assertEqual(self.create_project().status_code, 400)

    def test_import_rejects_a_relation_named_like_a_field(self):
        self.payload['relations'][0]['name'] = 'title'

        self.assertEqual(self.create_project().status_code, 400)

    def test_import_rejects_seed_rows_with_unknown_keys(self):
        self.payload['seeds'][0]['rows'] = [{'name': 'Le Guin', 'colour': 'red'}]

        self.assertEqual(self.create_project().status_code, 400)

    def test_import_accepts_numeric_and_boolean_defaults(self):
        self.payload['entities'][1]['fields'] = [
            {'name': 'pages', 'type': 'int', 'default': 100},
            {'name': 'is_read', 'type': 'bool', 'default': False},
        ]

        response = self.create_project()

        self.assertEqual(response.status_code, 201)
        defaults = {f['name']: f['default'] for e in response.data['entities'] for f in e['fields'] if e['name'] == 'Book'}
        self.assertEqual(defaults, {'pages': '100', 'is_read': 'false'})

    def test_codex_scaffold_returns_generated_files(self):
        project_id = self.create_project().data['id']

        response = self.client.get(f'/api/flux/codex/projects/{project_id}/scaffold/?target=django')

        self.assertEqual(response.status_code, 200)
        paths = [item['path'] for item in response.data['files']]
        self.assertIn('books/models.py', paths)
        self.assertIn('books/views.py', paths)
        self.assertIn('books/permissions.py', paths)

    def test_codex_scaffold_rejects_an_unknown_target(self):
        project_id = self.create_project().data['id']

        response = self.client.get(f'/api/flux/codex/projects/{project_id}/scaffold/?target=rust')

        self.assertEqual(response.status_code, 400)


class CodexStatusTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='codex-user', password='x')
        _token, plaintext = CodexToken.issue(self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'codex {plaintext}')
        plan = {
            'name': 'Plan',
            'milestones': [{'ref': 'm1', 'title': 'Beta'}],
            'tasks': [{'ref': 't1', 'title': 'Write docs', 'milestone_ref': 'm1'}],
        }
        self.project = self.client.post('/api/flux/codex/projects/', plan, format='json').data
        self.task_id = self.project['tasks'][0]['id']
        self.milestone_id = self.project['milestones'][0]['id']

    def test_set_task_status(self):
        response = self.client.patch(
            f'/api/flux/codex/projects/{self.project["id"]}/tasks/{self.task_id}/status/',
            {'status': 'done'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'done')
        self.assertEqual(Task.objects.get(pk=self.task_id).status, 'done')

    def test_set_milestone_status(self):
        response = self.client.patch(
            f'/api/flux/codex/projects/{self.project["id"]}/milestones/{self.milestone_id}/status/',
            {'status': 'in_progress'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Milestone.objects.get(pk=self.milestone_id).status, 'in_progress')

    def test_invalid_status_is_rejected(self):
        response = self.client.patch(
            f'/api/flux/codex/projects/{self.project["id"]}/tasks/{self.task_id}/status/',
            {'status': 'finished'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Task.objects.get(pk=self.task_id).status, 'not_started')

    def test_status_is_required(self):
        response = self.client.patch(
            f'/api/flux/codex/projects/{self.project["id"]}/tasks/{self.task_id}/status/', {}, format='json'
        )

        self.assertEqual(response.status_code, 400)

    def test_task_from_another_project_is_rejected(self):
        other = self.client.post(
            '/api/flux/codex/projects/', {'name': 'Other', 'tasks': [{'ref': 't', 'title': 'Elsewhere'}]}, format='json'
        ).data

        response = self.client.patch(
            f'/api/flux/codex/projects/{self.project["id"]}/tasks/{other["tasks"][0]["id"]}/status/',
            {'status': 'done'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)

    def test_cannot_set_status_in_someone_elses_project(self):
        stranger = User.objects.create_user(username='stranger', password='x')
        foreign = Project.objects.create(name='Not yours')
        foreign.members.add(stranger)
        task = Task.objects.create(project=foreign, title='Secret')

        response = self.client.patch(
            f'/api/flux/codex/projects/{foreign.pk}/tasks/{task.pk}/status/', {'status': 'done'}, format='json'
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Task.objects.get(pk=task.pk).status, 'not_started')
