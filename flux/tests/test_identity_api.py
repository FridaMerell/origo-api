from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from accounts.models import CodexToken
from flux.models import Project, Task, VisualProfile

User = get_user_model()

COLORS = [
    {'name': 'Primary', 'role': 'primary', 'light': '#0b5fff', 'dark': '#6b9dff'},
    {'name': 'Background', 'role': 'background', 'light': '#ffffff', 'dark': '#0b0d12'},
    {'name': 'Text', 'role': 'text', 'light': '#111318', 'dark': '#f2f3f5'},
]


def make_profile(owner, name='Origo', **overrides):
    return VisualProfile.objects.create(owner=owner, name=name, colors=COLORS, heading_font='Inter', **overrides)


class IdentityApiTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='owner', password='x')
        self.colleague = User.objects.create_user(username='colleague', password='x')
        self.outsider = User.objects.create_user(username='outsider', password='x')
        self.client = APIClient()
        self.client.force_authenticate(user=self.owner)
        self.profile = make_profile(self.owner)
        self.project = Project.objects.create(name='Origo Apsis')
        self.project.members.add(self.owner, self.colleague)

    def as_user(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_create_identity_sets_the_owner(self):
        response = self.client.post(
            '/api/flux/identities/', {'name': 'Nordic', 'colors': COLORS, 'body_font': 'Inter'}, format='json'
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(VisualProfile.objects.get(name='Nordic').owner, self.owner)

    def test_invalid_input_is_rejected(self):
        cases = [
            {'colors': [{'name': 'A', 'light': 'red'}]},
            {'heading_font': 'Inter"; } body { display:none'},
            {'font_import_url': 'http://insecure.example/f.css'},
            {'shadows': {'card': '0 0 1px red; } body { color: red'}},
            {'radii': {'sm': -4}},
            {'assets': [{'name': 'x', 'url': 'javascript:alert(1)'}]},
            {'base_font_size': 400},
            {'type_scale_ratio': '5'},
        ]
        for case in cases:
            with self.subTest(case=case):
                response = self.client.post('/api/flux/identities/', {'name': 'Bad', **case}, format='json')
                self.assertEqual(response.status_code, 400)

    def test_both_modes_is_the_default_and_needs_dark_values(self):
        light_only = [{'name': 'Text', 'role': 'text', 'light': '#111111'}]

        response = self.client.post('/api/flux/identities/', {'name': 'Half', 'colors': light_only}, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('colors', response.data)

    def test_light_only_identity_needs_no_dark_values(self):
        response = self.client.post(
            '/api/flux/identities/',
            {'name': 'Light', 'theme_modes': 'light', 'colors': [{'name': 'Text', 'role': 'text', 'light': '#111111'}]},
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['theme_modes'], 'light')

    def test_dark_only_identity_needs_no_light_values(self):
        response = self.client.post(
            '/api/flux/identities/',
            {'name': 'Night', 'theme_modes': 'dark', 'colors': [{'name': 'Text', 'role': 'text', 'dark': '#eeeeee'}]},
            format='json',
        )

        self.assertEqual(response.status_code, 201)

    def test_switching_to_both_modes_revalidates_the_existing_colors(self):
        light = self.client.post(
            '/api/flux/identities/',
            {'name': 'Light', 'theme_modes': 'light', 'colors': [{'name': 'Text', 'role': 'text', 'light': '#111111'}]},
            format='json',
        ).data

        response = self.client.patch(f'/api/flux/identities/{light["id"]}/', {'theme_modes': 'both'}, format='json')

        self.assertEqual(response.status_code, 400)

    def test_adding_dark_values_together_with_both_modes_is_accepted(self):
        light = self.client.post(
            '/api/flux/identities/',
            {'name': 'Light', 'theme_modes': 'light', 'colors': [{'name': 'Text', 'role': 'text', 'light': '#111111'}]},
            format='json',
        ).data

        response = self.client.patch(
            f'/api/flux/identities/{light["id"]}/',
            {'theme_modes': 'both', 'default_mode': 'dark', 'colors': [{'name': 'Text', 'role': 'text', 'light': '#111111', 'dark': '#eeeeee'}]},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['default_mode'], 'dark')

    def test_unknown_modes_and_asset_modes_are_rejected(self):
        for case in (
            {'theme_modes': 'sepia'},
            {'default_mode': 'sepia'},
            {'assets': [{'name': 'Logo', 'url': '/l.svg', 'mode': 'sepia'}]},
            {'shadows_dark': {'card': '0 0 1px red; } body { color: red'}},
        ):
            with self.subTest(case=case):
                response = self.client.post('/api/flux/identities/', {'name': 'Bad', 'colors': COLORS, **case}, format='json')
                self.assertEqual(response.status_code, 400)

    def test_asset_mode_and_dark_shadows_are_stored(self):
        response = self.client.post(
            '/api/flux/identities/',
            {
                'name': 'Rich', 'colors': COLORS,
                'assets': [{'name': 'Logo', 'url': '/d.svg', 'mode': 'dark'}],
                'shadows': {'card': '0 1px 2px rgba(0,0,0,0.2)'}, 'shadows_dark': {'card': '0 1px 2px rgba(0,0,0,0.8)'},
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['assets'][0]['mode'], 'dark')
        self.assertEqual(response.data['shadows_dark'], {'card': '0 1px 2px rgba(0,0,0,0.8)'})

    def test_design_scaffold_reflects_the_default_mode(self):
        self.profile.default_mode = 'dark'
        self.profile.save()
        self.project.identity = self.profile
        self.project.include_identity = True
        self.project.save()

        response = self.client.get(f'/api/flux/projects/{self.project.pk}/scaffold/?target=design')

        css = next(item['content'] for item in response.data['files'] if item['path'] == 'identity/tokens.css')
        self.assertIn(':root {\n  color-scheme: dark;', css)

    def test_identity_names_are_unique_per_owner(self):
        response = self.client.post('/api/flux/identities/', {'name': 'Origo'}, format='json')

        self.assertEqual(response.status_code, 400)

    def test_only_the_owner_and_users_of_projects_that_use_it_can_read(self):
        self.project.identity = self.profile
        self.project.include_identity = True
        self.project.save()

        self.assertEqual(len(self.as_user(self.colleague).get('/api/flux/identities/').data), 1)
        self.assertEqual(self.as_user(self.outsider).get('/api/flux/identities/').data, [])
        self.assertEqual(self.as_user(self.outsider).get(f'/api/flux/identities/{self.profile.pk}/').status_code, 404)

    def test_a_colleague_cannot_change_or_delete_the_identity(self):
        self.project.identity = self.profile
        self.project.include_identity = True
        self.project.save()
        colleague = self.as_user(self.colleague)

        self.assertEqual(colleague.patch(f'/api/flux/identities/{self.profile.pk}/', {'name': 'Mine'}, format='json').status_code, 404)
        self.assertEqual(colleague.delete(f'/api/flux/identities/{self.profile.pk}/').status_code, 404)

    def test_project_can_opt_in_with_an_owned_identity(self):
        response = self.client.patch(
            f'/api/flux/projects/{self.project.pk}/',
            {'include_identity': True, 'identity': self.profile.pk},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['include_identity'])
        self.assertEqual(response.data['identity'], self.profile.pk)

    def test_project_cannot_use_someone_elses_identity(self):
        theirs = make_profile(self.outsider, name='Theirs')

        response = self.client.patch(
            f'/api/flux/projects/{self.project.pk}/',
            {'include_identity': True, 'identity': theirs.pk},
            format='json',
        )

        self.assertEqual(response.status_code, 400)

    def test_opting_out_clears_the_identity(self):
        self.project.identity = self.profile
        self.project.include_identity = True
        self.project.save()

        response = self.client.patch(f'/api/flux/projects/{self.project.pk}/', {'include_identity': False}, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['identity'])
        self.assertFalse(response.data['include_identity'])

    def test_an_identity_without_opting_in_is_ignored(self):
        response = self.client.patch(f'/api/flux/projects/{self.project.pk}/', {'identity': self.profile.pk}, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['identity'])

    def test_projects_do_not_include_an_identity_by_default(self):
        response = self.client.get(f'/api/flux/projects/{self.project.pk}/')

        self.assertFalse(response.data['include_identity'])
        self.assertIsNone(response.data['identity'])

    def test_deleting_an_identity_keeps_the_project(self):
        self.project.identity = self.profile
        self.project.include_identity = True
        self.project.save()

        self.assertEqual(self.client.delete(f'/api/flux/identities/{self.profile.pk}/').status_code, 204)

        self.project.refresh_from_db()
        self.assertIsNone(self.project.identity)

    def test_design_scaffold_is_refused_for_projects_without_identity(self):
        response = self.client.get(f'/api/flux/projects/{self.project.pk}/scaffold/?target=design')

        self.assertEqual(response.status_code, 400)

    def test_design_scaffold_is_refused_when_opted_in_without_choosing_one(self):
        self.project.include_identity = True
        self.project.save()

        response = self.client.get(f'/api/flux/projects/{self.project.pk}/scaffold/?target=design')

        self.assertEqual(response.status_code, 400)

    def test_design_scaffold_returns_the_identity_files(self):
        self.project.identity = self.profile
        self.project.include_identity = True
        self.project.save()

        response = self.client.get(f'/api/flux/projects/{self.project.pk}/scaffold/?target=design')

        self.assertEqual(response.status_code, 200)
        paths = [item['path'] for item in response.data['files']]
        self.assertIn('identity/tokens.css', paths)
        self.assertIn('identity/tailwind.theme.css', paths)
        self.assertIn('identity/STYLEGUIDE.md', paths)

    def test_a_deactivated_identity_is_not_used_by_the_scaffold(self):
        self.project.identity = self.profile
        self.project.include_identity = False
        self.project.save()

        response = self.client.get(f'/api/flux/projects/{self.project.pk}/scaffold/?target=design')

        self.assertEqual(response.status_code, 400)

    def test_generate_tasks_adds_an_identity_task_only_when_included(self):
        url = f'/api/flux/projects/{self.project.pk}/generate-tasks/'
        self.assertFalse(Task.objects.filter(title__startswith='Identitet').exists())
        self.client.post(url)
        self.assertFalse(Task.objects.filter(title__startswith='Identitet').exists())

        self.project.identity = self.profile
        self.project.include_identity = True
        self.project.save()
        self.client.post(url)

        self.assertTrue(Task.objects.filter(project=self.project, title='Identitet: Origo').exists())


class CodexIdentityTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='codex-user', password='x')
        _token, plaintext = CodexToken.issue(self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'codex {plaintext}')
        self.identity = {'name': 'Origo', 'colors': COLORS, 'heading_font': 'Inter', 'icon_library': 'lucide'}

    def test_plan_can_create_and_attach_an_identity(self):
        response = self.client.post(
            '/api/flux/codex/projects/', {'name': 'App', 'identity': self.identity}, format='json'
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data['include_identity'])
        profile = VisualProfile.objects.get(name='Origo')
        self.assertEqual(profile.owner, self.user)
        self.assertEqual(response.data['identity_id'], profile.pk)

    def test_plan_can_reuse_an_identity_you_own(self):
        profile = make_profile(self.user)

        response = self.client.post(
            '/api/flux/codex/projects/', {'name': 'App', 'identity_id': profile.pk}, format='json'
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['identity_id'], profile.pk)
        self.assertEqual(VisualProfile.objects.count(), 1)

    def test_plan_cannot_use_someone_elses_identity(self):
        stranger = User.objects.create_user(username='stranger', password='x')
        theirs = make_profile(stranger, name='Theirs')

        response = self.client.post(
            '/api/flux/codex/projects/', {'name': 'App', 'identity_id': theirs.pk}, format='json'
        )

        self.assertEqual(response.status_code, 400)

    def test_projects_have_no_identity_unless_asked(self):
        response = self.client.post('/api/flux/codex/projects/', {'name': 'Plain'}, format='json')

        self.assertFalse(response.data['include_identity'])
        self.assertIsNone(response.data['identity_id'])

    def test_include_identity_false_clears_a_chosen_identity(self):
        profile = make_profile(self.user)

        response = self.client.post(
            '/api/flux/codex/projects/',
            {'name': 'App', 'identity_id': profile.pk, 'include_identity': False},
            format='json',
        )

        self.assertFalse(response.data['include_identity'])
        self.assertIsNone(response.data['identity_id'])

    def test_include_identity_must_be_a_boolean(self):
        response = self.client.post(
            '/api/flux/codex/projects/', {'name': 'App', 'include_identity': 'yes'}, format='json'
        )

        self.assertEqual(response.status_code, 400)

    def test_plan_identity_supports_modes_and_rejects_missing_dark_values(self):
        light = {'name': 'Light', 'theme_modes': 'light', 'colors': [{'name': 'Text', 'role': 'text', 'light': '#111111'}]}

        ok = self.client.post('/api/flux/codex/projects/', {'name': 'A', 'identity': light}, format='json')
        both = {**light, 'name': 'Both', 'theme_modes': 'both'}
        rejected = self.client.post('/api/flux/codex/projects/', {'name': 'B', 'identity': both}, format='json')

        self.assertEqual(ok.status_code, 201)
        self.assertEqual(VisualProfile.objects.get(name='Light').theme_modes, 'light')
        self.assertEqual(rejected.status_code, 400)
        self.assertFalse(Project.objects.filter(name='B').exists())

    def test_plan_identity_rejects_unknown_modes(self):
        for case in ({'theme_modes': 'sepia'}, {'default_mode': 'sepia'}):
            with self.subTest(case=case):
                response = self.client.post(
                    '/api/flux/codex/projects/', {'name': 'C', 'identity': {**self.identity, **case}}, format='json'
                )
                self.assertEqual(response.status_code, 400)

    def test_listed_identities_include_the_mode_settings(self):
        make_profile(self.user, theme_modes='both', default_mode='dark', shadows_dark={'card': '0 0 1px #000'})

        listed = self.client.get('/api/flux/codex/identities/').data[0]

        self.assertEqual((listed['theme_modes'], listed['default_mode']), ('both', 'dark'))
        self.assertEqual(listed['shadows_dark'], {'card': '0 0 1px #000'})

    def test_duplicate_identity_name_is_rejected(self):
        make_profile(self.user)

        response = self.client.post(
            '/api/flux/codex/projects/', {'name': 'App', 'identity': self.identity}, format='json'
        )

        self.assertEqual(response.status_code, 400)

    def test_invalid_identity_rolls_the_project_back(self):
        self.identity['colors'] = [{'name': 'A', 'light': 'red'}]

        response = self.client.post(
            '/api/flux/codex/projects/', {'name': 'App', 'identity': self.identity}, format='json'
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Project.objects.filter(name='App').exists())
        self.assertEqual(VisualProfile.objects.count(), 0)

    def test_list_identities_only_returns_your_own(self):
        make_profile(self.user)
        stranger = User.objects.create_user(username='stranger', password='x')
        make_profile(stranger, name='Theirs')

        response = self.client.get('/api/flux/codex/identities/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['name'] for item in response.data], ['Origo'])
        self.assertEqual(response.data[0]['type_scale_ratio'], 1.25)

    def test_codex_scaffold_supports_the_design_target(self):
        created = self.client.post(
            '/api/flux/codex/projects/', {'name': 'App', 'identity': self.identity}, format='json'
        ).data

        response = self.client.get(f'/api/flux/codex/projects/{created["id"]}/scaffold/?target=design')

        self.assertEqual(response.status_code, 200)
        self.assertIn('identity/tokens.css', [item['path'] for item in response.data['files']])

    def test_codex_scaffold_design_is_refused_without_an_identity(self):
        created = self.client.post('/api/flux/codex/projects/', {'name': 'Plain'}, format='json').data

        response = self.client.get(f'/api/flux/codex/projects/{created["id"]}/scaffold/?target=design')

        self.assertEqual(response.status_code, 400)
