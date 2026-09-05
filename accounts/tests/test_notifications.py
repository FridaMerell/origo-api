from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from accounts.models import Notification

User = get_user_model()


class NotificationViewSetTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='frida', password='x')
        self.other = User.objects.create_user(username='other', password='x')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_list_only_returns_the_current_user_notifications(self):
        Notification.objects.create(user=self.user, domain='flux', message='mine')
        Notification.objects.create(user=self.other, domain='flux', message='not mine')

        response = self.client.get('/api/accounts/notifications/')

        messages = [row['message'] for row in response.data]
        self.assertEqual(messages, ['mine'])

    def test_unread_filter(self):
        Notification.objects.create(user=self.user, domain='flux', message='read', is_read=True)
        Notification.objects.create(user=self.user, domain='flux', message='unread', is_read=False)

        response = self.client.get('/api/accounts/notifications/', {'unread': 'true'})

        messages = [row['message'] for row in response.data]
        self.assertEqual(messages, ['unread'])

    def test_summary_reports_unread_count_and_latest(self):
        Notification.objects.create(user=self.user, domain='flux', message='a', is_read=True)
        Notification.objects.create(user=self.user, domain='verso', message='b', is_read=False)
        Notification.objects.create(user=self.other, domain='flux', message='not mine', is_read=False)

        response = self.client.get('/api/accounts/notifications/summary/')

        self.assertEqual(response.data['unread_count'], 1)
        self.assertEqual(len(response.data['latest']), 2)

    def test_read_action_marks_a_single_notification(self):
        notification = Notification.objects.create(user=self.user, domain='flux', message='a')

        response = self.client.post(f'/api/accounts/notifications/{notification.pk}/read/')

        self.assertEqual(response.status_code, 200)
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)

    def test_cannot_mark_another_users_notification_as_read(self):
        notification = Notification.objects.create(user=self.other, domain='flux', message='a')

        response = self.client.post(f'/api/accounts/notifications/{notification.pk}/read/')

        self.assertEqual(response.status_code, 404)

    def test_read_all_marks_every_unread_notification(self):
        Notification.objects.create(user=self.user, domain='flux', message='a')
        Notification.objects.create(user=self.user, domain='flux', message='b')

        response = self.client.post('/api/accounts/notifications/read-all/')

        self.assertEqual(response.data['marked_read'], 2)
        self.assertEqual(Notification.objects.filter(user=self.user, is_read=False).count(), 0)
