from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from accounts.models import Invitation
from flux.models import Project
from verso.models import House

User = get_user_model()


class InvitationCreateTests(APITestCase):
    def setUp(self):
        self.member = User.objects.create_user(username='member', password='x')
        self.outsider = User.objects.create_user(username='outsider', password='x')
        self.house = House.objects.create(name='Home')
        self.house.members.add(self.member)

    def test_member_can_create_an_invitation_for_their_house(self):
        client = APIClient()
        client.force_authenticate(user=self.member)

        response = client.post('/api/accounts/invitations/', {'house': self.house.pk})

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data['token'])
        self.assertEqual(Invitation.objects.count(), 1)

    def test_non_member_cannot_create_an_invitation_for_the_house(self):
        client = APIClient()
        client.force_authenticate(user=self.outsider)

        response = client.post('/api/accounts/invitations/', {'house': self.house.pk})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Invitation.objects.count(), 0)

    def test_cannot_target_both_house_and_project(self):
        project = Project.objects.create(name='Origo')
        project.members.add(self.member)
        client = APIClient()
        client.force_authenticate(user=self.member)

        response = client.post(
            '/api/accounts/invitations/',
            {'house': self.house.pk, 'project': project.pk},
        )

        self.assertEqual(response.status_code, 400)


class InvitationRedeemTests(APITestCase):
    def setUp(self):
        self.creator = User.objects.create_user(username='creator', password='x')
        self.house = House.objects.create(name='Home')
        self.house.members.add(self.creator)
        self.invitation, self.plaintext = Invitation.issue(house=self.house, created_by=self.creator)

    def test_anonymous_redeem_creates_an_account_and_joins(self):
        client = APIClient()

        response = client.post(
            '/api/accounts/invitations/redeem/',
            {'token': self.plaintext, 'username': 'newcomer', 'password': 'a-strong-passphrase-1'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['created'])
        newcomer = User.objects.get(username='newcomer')
        self.assertIn(newcomer, self.house.members.all())

    def test_authenticated_redeem_joins_without_new_account(self):
        member = User.objects.create_user(username='member', password='x')
        client = APIClient()
        client.force_authenticate(user=member)

        response = client.post('/api/accounts/invitations/redeem/', {'token': self.plaintext})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['created'])
        self.assertIn(member, self.house.members.all())

    def test_revoked_invitation_cannot_be_redeemed(self):
        self.invitation.revoke()
        client = APIClient()

        response = client.post(
            '/api/accounts/invitations/redeem/',
            {'token': self.plaintext, 'username': 'newcomer', 'password': 'a-strong-passphrase-1'},
        )

        self.assertEqual(response.status_code, 400)

    def test_expired_invitation_cannot_be_redeemed(self):
        Invitation.objects.filter(pk=self.invitation.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        client = APIClient()

        response = client.post(
            '/api/accounts/invitations/redeem/',
            {'token': self.plaintext, 'username': 'newcomer', 'password': 'a-strong-passphrase-1'},
        )

        self.assertEqual(response.status_code, 400)

    def test_unknown_token_is_rejected(self):
        client = APIClient()

        response = client.post(
            '/api/accounts/invitations/redeem/',
            {'token': 'not-a-real-token', 'username': 'newcomer', 'password': 'a-strong-passphrase-1'},
        )

        self.assertEqual(response.status_code, 400)


class InvitationRevokeTests(APITestCase):
    def setUp(self):
        self.creator = User.objects.create_user(username='creator', password='x')
        self.house = House.objects.create(name='Home')
        self.house.members.add(self.creator)
        self.invitation, self.plaintext = Invitation.issue(house=self.house, created_by=self.creator)

    def test_house_member_can_revoke_an_invitation(self):
        client = APIClient()
        client.force_authenticate(user=self.creator)

        response = client.post(f'/api/accounts/invitations/{self.invitation.pk}/revoke/')

        self.assertEqual(response.status_code, 200)
        self.invitation.refresh_from_db()
        self.assertFalse(self.invitation.is_active)

    def test_delete_also_revokes_instead_of_deleting_the_row(self):
        client = APIClient()
        client.force_authenticate(user=self.creator)

        response = client.delete(f'/api/accounts/invitations/{self.invitation.pk}/')

        self.assertEqual(response.status_code, 204)
        self.assertTrue(Invitation.objects.filter(pk=self.invitation.pk).exists())
        self.invitation.refresh_from_db()
        self.assertFalse(self.invitation.is_active)
