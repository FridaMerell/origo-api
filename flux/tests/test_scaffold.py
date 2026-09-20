"""Scaffold generators are pure functions over a spec dict, so these tests need no database."""

import ast
import json
import unittest

from flux.services.scaffold import ScaffoldError, generate_files


def field(name, type='string', **overrides):
    return {
        'name': name, 'type': type, 'description': '', 'nullable': False,
        'unique': False, 'default': '', 'max_length': None, **overrides,
    }


def relation(name, target, kind='fk', **overrides):
    return {
        'name': name, 'target': target, 'kind': kind, 'related_name': '',
        'on_delete': 'cascade', 'nullable': False, 'description': '', **overrides,
    }


def make_spec(**overrides):
    spec = {
        'project': {'name': 'Book Club', 'description': 'Track books.'},
        'stack': {
            'targets': ['django', 'typescript', 'csharp'], 'api_naming': 'snake_case',
            'auth_method': 'session', 'database': 'postgresql', 'app_label': '', 'namespace': '',
        },
        'entities': [
            {
                'name': 'Author', 'description': 'A writer',
                'fields': [field('name', max_length=120), field('born_at', 'date', nullable=True)],
                'relations': [],
            },
            {
                'name': 'Book', 'description': '',
                'fields': [field('title'), field('pages', 'int', default='100')],
                'relations': [
                    relation('author', 'Author', related_name='books'),
                    relation('editor', 'Author', on_delete='set_null'),
                    relation('reviewers', 'Author', kind='m2m'),
                ],
            },
        ],
        'resources': [
            {'entity': 'Author', 'path': 'authors', 'operations': ['list', 'retrieve'], 'filters': ['name'], 'ordering': 'name'},
            {'entity': 'Book', 'path': 'books', 'operations': ['list', 'create', 'delete'], 'filters': [], 'ordering': ''},
        ],
        'roles': [],
        'screens': [],
        'integrations': [],
        'seeds': [],
    }
    spec.update(overrides)
    return spec


def files_by_path(spec, target):
    return {item['path']: item['content'] for item in generate_files(spec, target)}


class DjangoGeneratorTests(unittest.TestCase):
    def test_generated_python_is_valid(self):
        for path, content in files_by_path(make_spec(), 'django').items():
            ast.parse(content, path)

    def test_models_map_types_and_options(self):
        models = files_by_path(make_spec(), 'django')['book_club/models.py']

        self.assertIn("name = models.CharField(max_length=120)", models)
        self.assertIn("born_at = models.DateField(null=True, blank=True)", models)
        self.assertIn("pages = models.IntegerField(default=100)", models)

    def test_relations_get_unique_related_names_when_targets_repeat(self):
        models = files_by_path(make_spec(), 'django')['book_club/models.py']

        self.assertIn("models.ForeignKey('Author', on_delete=models.CASCADE, related_name='books')", models)
        self.assertIn("related_name='book_editor_set'", models)
        self.assertIn("related_name='book_reviewers_set'", models)

    def test_set_null_relation_is_nullable(self):
        models = files_by_path(make_spec(), 'django')['book_club/models.py']

        self.assertIn("on_delete=models.SET_NULL, related_name='book_editor_set', null=True, blank=True", models)

    def test_viewsets_only_include_the_selected_operations(self):
        views = files_by_path(make_spec(), 'django')['book_club/views.py']
        book = views.split('class BookViewSet')[1]

        self.assertIn('mixins.CreateModelMixin', book)
        self.assertIn('mixins.DestroyModelMixin', book)
        self.assertNotIn('mixins.UpdateModelMixin', book)
        self.assertNotIn('mixins.RetrieveModelMixin', book)

    def test_permissions_file_is_only_generated_with_roles(self):
        self.assertNotIn('book_club/permissions.py', files_by_path(make_spec(), 'django'))

        roles = [{'name': 'reader', 'permissions': [{'resource': 'Book', 'operation': 'list', 'scope': 'all'}]}]
        files = files_by_path(make_spec(roles=roles), 'django')

        self.assertIn('book_club/permissions.py', files)
        self.assertIn('RolePermission', files['book_club/views.py'])

    def test_fixtures_are_valid_json_with_pk_and_snake_case_fields(self):
        seeds = [{'entity': 'Author', 'rows': [{'name': 'Le Guin', 'bornAt': '1929-10-21'}]}]
        files = files_by_path(make_spec(seeds=seeds), 'django')

        records = json.loads(files['book_club/fixtures/author.json'])

        self.assertEqual(records, [{'model': 'book_club.author', 'pk': 1, 'fields': {'name': 'Le Guin', 'born_at': '1929-10-21'}}])

    def test_app_label_comes_from_the_stack_profile(self):
        spec = make_spec()
        spec['stack']['app_label'] = 'library'

        self.assertIn('library/models.py', files_by_path(spec, 'django'))

    def test_unsupported_default_is_reported(self):
        spec = make_spec()
        spec['entities'][1]['fields'][1]['default'] = 'abc'

        with self.assertRaises(ScaffoldError):
            generate_files(spec, 'django')


class TypeScriptGeneratorTests(unittest.TestCase):
    def test_interfaces_use_nullable_unions_and_relation_ids(self):
        types = files_by_path(make_spec(), 'typescript')['types.ts']

        self.assertIn('born_at: string | null;', types)
        self.assertIn('author: number;', types)
        self.assertIn('editor: number | null;', types)
        self.assertIn('reviewers: number[];', types)

    def test_camel_case_naming(self):
        spec = make_spec()
        spec['stack']['api_naming'] = 'camel_case'

        self.assertIn('bornAt: string | null;', files_by_path(spec, 'typescript')['types.ts'])

    def test_api_client_only_has_selected_operations(self):
        api = files_by_path(make_spec(), 'typescript')['api.ts']
        book = api.split('export const bookApi')[1]

        self.assertIn('create:', book)
        self.assertIn('remove:', book)
        self.assertNotIn('update:', book)

    def test_routes_file_needs_screens(self):
        self.assertNotIn('routes.ts', files_by_path(make_spec(), 'typescript'))

        screens = [{'name': 'Books', 'route': '/books', 'description': '', 'entities': ['Book'], 'parent': None}]

        self.assertIn('routes.ts', files_by_path(make_spec(screens=screens), 'typescript'))


class CSharpGeneratorTests(unittest.TestCase):
    def test_classes_use_nullable_types_and_navigation_properties(self):
        author = files_by_path(make_spec(), 'csharp')['Models/Author.cs']
        book = files_by_path(make_spec(), 'csharp')['Models/Book.cs']

        self.assertIn('public DateOnly? BornAt { get; set; }', author)
        self.assertIn('public string Title { get; set; } = string.Empty;', book)
        self.assertIn('public int AuthorId { get; set; }', book)
        self.assertIn('public Author? Author { get; set; }', book)
        self.assertIn('public int? EditorId { get; set; }', book)
        self.assertIn('public ICollection<Author> Reviewers { get; set; } = new List<Author>();', book)

    def test_namespace_defaults_to_the_project_name(self):
        self.assertIn('namespace BookClub.Models;', files_by_path(make_spec(), 'csharp')['Models/Book.cs'])

    def test_controllers_and_context_need_resources(self):
        files = files_by_path(make_spec(), 'csharp')

        self.assertIn('Data/AppDbContext.cs', files)
        self.assertIn('Controllers/BookController.cs', files)
        self.assertNotIn('HttpPut', files['Controllers/BookController.cs'])


class SkeletonGeneratorTests(unittest.TestCase):
    def test_env_example_includes_integration_variables(self):
        integrations = [{'name': 'Stripe', 'kind': 'payment', 'env_vars': ['STRIPE_KEY']}]
        env = files_by_path(make_spec(integrations=integrations), 'skeleton')['.env.example']

        self.assertIn('STRIPE_KEY=', env)
        self.assertIn('DATABASE_URL=postgres://', env)

    def test_backend_files_follow_the_selected_targets(self):
        django = files_by_path(make_spec(), 'skeleton')
        csharp_spec = make_spec()
        csharp_spec['stack']['targets'] = ['csharp']
        csharp = files_by_path(csharp_spec, 'skeleton')

        self.assertIn('requirements.txt', django)
        self.assertNotIn('requirements.txt', csharp)
        self.assertIn('dotnet', csharp['Dockerfile'])


class NamingTests(unittest.TestCase):
    def test_digits_stay_attached_to_the_word(self):
        spec = make_spec()
        spec['entities'][0]['fields'].append(field('address2'))
        spec['entities'][0]['fields'].append(field('lineOne'))

        models = files_by_path(spec, 'django')['book_club/models.py']

        self.assertIn('address2 = models.CharField', models)
        self.assertIn('line_one = models.CharField', models)


class DjangoProjectShapeTests(unittest.TestCase):
    def test_app_is_a_package_with_an_app_config(self):
        files = files_by_path(make_spec(), 'django')

        self.assertIn('book_club/__init__.py', files)
        self.assertIn('class BookClubConfig(AppConfig)', files['book_club/apps.py'])

    def test_invalid_decimal_default_is_reported(self):
        spec = make_spec()
        spec['entities'][1]['fields'].append(field('price', 'decimal', default='cheap'))

        with self.assertRaises(ScaffoldError):
            generate_files(spec, 'django')

    def test_viewsets_are_open_when_auth_is_none(self):
        spec = make_spec()
        spec['stack']['auth_method'] = 'none'

        views = files_by_path(spec, 'django')['book_club/views.py']

        self.assertIn('permissions.AllowAny', views)
        self.assertNotIn('IsAuthenticated', views)

    def test_resource_path_slashes_are_stripped_in_the_router(self):
        spec = make_spec()
        spec['resources'][0]['path'] = '/authors/'

        self.assertIn("router.register('authors',", files_by_path(spec, 'django')['book_club/urls.py'])


class TypeScriptClientTests(unittest.TestCase):
    def test_session_auth_sends_the_csrf_token(self):
        api = files_by_path(make_spec(), 'typescript')['api.ts']

        self.assertIn('X-CSRFToken', api)

    def test_jwt_auth_sends_a_bearer_token(self):
        spec = make_spec()
        spec['stack']['auth_method'] = 'jwt'

        api = files_by_path(spec, 'typescript')['api.ts']

        self.assertIn('export function setAuthToken', api)
        self.assertIn('Bearer', api)
        self.assertNotIn('X-CSRFToken', api)

    def test_auth_none_sends_no_auth_headers(self):
        spec = make_spec()
        spec['stack']['auth_method'] = 'none'

        api = files_by_path(spec, 'typescript')['api.ts']

        self.assertNotIn('Authorization', api)
        self.assertNotIn('X-CSRFToken', api)

    def test_route_strings_are_escaped(self):
        screens = [{'name': 'Say "hi"', 'route': '/hi', 'description': '', 'entities': [], 'parent': None}]

        routes = files_by_path(make_spec(screens=screens), 'typescript')['routes.ts']

        self.assertIn('name: "Say \\"hi\\""', routes)


class CSharpModelConfigurationTests(unittest.TestCase):
    def test_relations_are_configured_explicitly(self):
        context = files_by_path(make_spec(), 'csharp')['Data/AppDbContext.cs']

        self.assertIn('HasMany(e => e.Reviewers).WithMany();', context)
        self.assertIn('HasOne(e => e.Editor).WithMany().HasForeignKey(e => e.EditorId).OnDelete(DeleteBehavior.SetNull);', context)
        self.assertIn('HasOne(e => e.Author).WithMany().HasForeignKey(e => e.AuthorId).OnDelete(DeleteBehavior.Cascade);', context)

    def test_one_to_one_uses_a_unique_foreign_key(self):
        spec = make_spec()
        spec['entities'][1]['relations'].append(relation('profile', 'Author', kind='o2o', on_delete='protect'))

        context = files_by_path(spec, 'csharp')['Data/AppDbContext.cs']

        self.assertIn('HasOne(e => e.Profile).WithOne().HasForeignKey<Book>(e => e.ProfileId).OnDelete(DeleteBehavior.Restrict);', context)

    def test_context_exists_without_resources(self):
        files = files_by_path(make_spec(resources=[]), 'csharp')

        self.assertIn('Data/AppDbContext.cs', files)
        self.assertFalse([path for path in files if path.startswith('Controllers/')])

    def test_create_does_not_reference_a_missing_retrieve_action(self):
        spec = make_spec()
        spec['resources'][1]['operations'] = ['create']

        controller = files_by_path(spec, 'csharp')['Controllers/BookController.cs']

        self.assertNotIn('nameof(Retrieve)', controller)
        self.assertIn('return Created($"api/books/{item.Id}", item);', controller)

    def test_create_uses_created_at_action_when_retrieve_exists(self):
        spec = make_spec()
        spec['resources'][0]['operations'] = ['retrieve', 'create']

        controller = files_by_path(spec, 'csharp')['Controllers/AuthorController.cs']

        self.assertIn('CreatedAtAction(nameof(Retrieve)', controller)

    def test_authorize_is_omitted_when_auth_is_none(self):
        spec = make_spec()
        spec['stack']['auth_method'] = 'none'

        self.assertNotIn('[Authorize]', files_by_path(spec, 'csharp')['Controllers/BookController.cs'])
        self.assertIn('[Authorize]', files_by_path(make_spec(), 'csharp')['Controllers/BookController.cs'])


class SkeletonProjectFilesTests(unittest.TestCase):
    def test_django_skeleton_can_run_manage_py(self):
        files = files_by_path(make_spec(), 'skeleton')

        for path in ('manage.py', 'config/__init__.py', 'config/settings.py', 'config/urls.py'):
            self.assertIn(path, files)
        for path in ('manage.py', 'config/settings.py', 'config/urls.py'):
            ast.parse(files[path], path)
        self.assertIn('"book_club",', files['config/settings.py'])
        self.assertIn('include("book_club.urls")', files['config/urls.py'])

    def test_jwt_and_token_auth_get_login_endpoints(self):
        jwt_spec = make_spec()
        jwt_spec['stack']['auth_method'] = 'jwt'
        token_spec = make_spec()
        token_spec['stack']['auth_method'] = 'token'

        self.assertIn('TokenObtainPairView', files_by_path(jwt_spec, 'skeleton')['config/urls.py'])
        self.assertIn('obtain_auth_token', files_by_path(token_spec, 'skeleton')['config/urls.py'])
        self.assertIn('rest_framework.urls', files_by_path(make_spec(), 'skeleton')['config/urls.py'])

    def test_urls_only_include_the_app_when_it_has_resources(self):
        files = files_by_path(make_spec(resources=[]), 'skeleton')

        self.assertNotIn('book_club.urls', files['config/urls.py'])

    def test_token_and_camel_case_are_wired_into_django(self):
        spec = make_spec()
        spec['stack'].update(auth_method='token', api_naming='camel_case')

        files = files_by_path(spec, 'skeleton')

        self.assertIn('rest_framework.authtoken', files['config/settings.py'])
        self.assertIn('CamelCaseJSONRenderer', files['config/settings.py'])
        self.assertIn('djangorestframework-camel-case', files['requirements.txt'])

    def test_csharp_skeleton_has_project_file_and_program(self):
        spec = make_spec()
        spec['stack'].update(targets=['csharp'], database='postgresql')

        files = files_by_path(spec, 'skeleton')

        self.assertIn('BookClub.csproj', files)
        self.assertIn('Npgsql.EntityFrameworkCore.PostgreSQL', files['BookClub.csproj'])
        self.assertIn('UseNpgsql', files['Program.cs'])
        self.assertIn('8080:8080', files['docker-compose.yml'])
        self.assertIn('ConnectionStrings__Default=', files['.env.example'])

    def test_csharp_program_has_no_database_without_entities(self):
        spec = make_spec(entities=[], resources=[])
        spec['stack']['targets'] = ['csharp']

        self.assertNotIn('AppDbContext', files_by_path(spec, 'skeleton')['Program.cs'])


class ScaffoldDispatchTests(unittest.TestCase):
    def test_unknown_target_is_rejected(self):
        with self.assertRaises(ScaffoldError):
            generate_files(make_spec(), 'rust')
