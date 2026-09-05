from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

User = get_user_model()


class CSRFTokenTests(TestCase):
    def test_csrf_endpoint_is_open_and_returns_a_token(self):
        client = APIClient(enforce_csrf_checks=True)
        response = client.get('/api/accounts/csrf/')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['csrfToken'])


class LoginLogoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='frida', password='correct-horse')

    def test_login_with_valid_credentials_starts_a_session(self):
        client = APIClient()

        response = client.post(
            '/api/accounts/login/',
            {'username': 'frida', 'password': 'correct-horse'},
        )

        self.assertEqual(response.status_code, 204)
        me = client.get('/api/accounts/me/')
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.data['username'], 'frida')

    def test_login_with_wrong_password_is_rejected(self):
        client = APIClient()

        response = client.post(
            '/api/accounts/login/',
            {'username': 'frida', 'password': 'wrong'},
        )

        self.assertEqual(response.status_code, 400)

    def test_logout_requires_authentication(self):
        client = APIClient()

        response = client.post('/api/accounts/logout/')

        self.assertEqual(response.status_code, 401)

    def test_logout_ends_the_session(self):
        client = APIClient()
        client.force_authenticate(user=self.user)

        response = client.post('/api/accounts/logout/')

        self.assertEqual(response.status_code, 204)


class MeViewTests(TestCase):
    def test_me_requires_authentication(self):
        client = APIClient()

        response = client.get('/api/accounts/me/')

        self.assertEqual(response.status_code, 401)

    def test_me_returns_the_current_user(self):
        user = User.objects.create_user(username='frida', password='x')
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get('/api/accounts/me/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['username'], 'frida')
        self.assertEqual(response.data['open_notifications'], 0)
