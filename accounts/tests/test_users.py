from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient, APITestCase

from flux.models import Project
from verso.models import House

User = get_user_model()


class UserViewSetTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='frida', password='x')
        self.housemate = User.objects.create_user(username='housemate', password='x')
        self.stranger = User.objects.create_user(username='stranger', password='x')

        house = House.objects.create(name='Home')
        house.members.add(self.user, self.housemate)

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_list_only_returns_users_who_share_a_group(self):
        response = self.client.get('/api/accounts/users/')

        usernames = {row['username'] for row in response.data['results']}
        self.assertEqual(usernames, {'housemate'})

    def test_list_excludes_the_requesting_user(self):
        response = self.client.get('/api/accounts/users/')

        usernames = {row['username'] for row in response.data['results']}
        self.assertNotIn('frida', usernames)

    def test_shared_flux_project_also_counts_as_a_group(self):
        project = Project.objects.create(name='Origo')
        project.members.add(self.user, self.stranger)

        response = self.client.get('/api/accounts/users/')

        usernames = {row['username'] for row in response.data['results']}
        self.assertIn('stranger', usernames)


class SelfViewSetTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='frida', password='correct-horse')
        self.other = User.objects.create_user(username='other', password='x')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_list_only_ever_returns_the_current_user(self):
        response = self.client.get('/api/accounts/self/')

        usernames = [row['username'] for row in response.data]
        self.assertEqual(usernames, ['frida'])

    def test_set_password_requires_the_correct_current_password(self):
        response = self.client.post(
            '/api/accounts/self/set-password/',
            {'current_password': 'wrong', 'new_password': 'a-new-passphrase-99'},
        )

        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('correct-horse'))

    def test_set_password_changes_the_password_on_success(self):
        response = self.client.post(
            '/api/accounts/self/set-password/',
            {'current_password': 'correct-horse', 'new_password': 'a-new-passphrase-99'},
        )

        self.assertEqual(response.status_code, 204)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('a-new-passphrase-99'))

    def test_token_action_issues_and_reuses_a_token(self):
        first = self.client.get('/api/accounts/self/token/')
        second = self.client.get('/api/accounts/self/token/')

        self.assertEqual(first.data['token'], second.data['token'])
        self.assertEqual(Token.objects.filter(user=self.user).count(), 1)

    def test_token_rotate_issues_a_new_token(self):
        first = self.client.get('/api/accounts/self/token/').data['token']

        rotated = self.client.post('/api/accounts/self/token/?rotate=1').data['token']

        self.assertNotEqual(first, rotated)
        self.assertEqual(Token.objects.filter(user=self.user).count(), 1)

    def test_token_delete_revokes_it(self):
        self.client.get('/api/accounts/self/token/')

        response = self.client.delete('/api/accounts/self/token/')

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Token.objects.filter(user=self.user).exists())
