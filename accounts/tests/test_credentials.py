from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.authentication import CodexTokenAuthentication
from accounts.models import CodexToken

User = get_user_model()


class CodexTokenIssueAndAuthenticateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='frida', password='x')

    def test_issue_returns_the_plaintext_exactly_once(self):
        token, plaintext = CodexToken.issue(self.user)

        self.assertNotEqual(token.token_hash, plaintext)
        self.assertEqual(token.token_hash, CodexToken.hash_value(plaintext))

    def test_authenticate_accepts_the_issued_plaintext(self):
        _token, plaintext = CodexToken.issue(self.user)

        found = CodexToken.authenticate(plaintext)

        self.assertIsNotNone(found)
        self.assertEqual(found.user, self.user)

    def test_authenticate_rejects_an_unknown_token(self):
        self.assertIsNone(CodexToken.authenticate('not-a-real-token'))

    def test_authenticate_rejects_a_revoked_token(self):
        token, plaintext = CodexToken.issue(self.user)
        token.revoke()

        self.assertIsNone(CodexToken.authenticate(plaintext))

    def test_authenticate_rejects_an_expired_token(self):
        token, plaintext = CodexToken.issue(
            self.user, expires_at=timezone.now() - timedelta(minutes=1)
        )

        self.assertIsNone(CodexToken.authenticate(plaintext))

    def test_authenticate_updates_last_used_at(self):
        _token, plaintext = CodexToken.issue(self.user)

        found = CodexToken.authenticate(plaintext)

        self.assertIsNotNone(found.last_used_at)

    def test_revoke_is_idempotent(self):
        token, _plaintext = CodexToken.issue(self.user)
        token.revoke()
        first_revoked_at = token.revoked_at

        token.revoke()

        self.assertEqual(token.revoked_at, first_revoked_at)


class CodexTokenAuthenticationBackendTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='frida', password='x')
        self.backend = CodexTokenAuthentication()

    def test_missing_authorization_header_is_ignored(self):
        request = _FakeRequest(b'')

        self.assertIsNone(self.backend.authenticate(request))

    def test_wrong_scheme_is_ignored(self):
        request = _FakeRequest(b'Bearer sometoken')

        self.assertIsNone(self.backend.authenticate(request))

    def test_valid_codex_token_authenticates(self):
        _token, plaintext = CodexToken.issue(self.user)
        request = _FakeRequest(f'codex {plaintext}'.encode())

        user, token = self.backend.authenticate(request)

        self.assertEqual(user, self.user)
        self.assertEqual(token.user, self.user)


class _FakeRequest:
    """Minimal stand-in exposing the ``META`` DRF's header helper reads."""

    def __init__(self, authorization_header):
        self.META = {'HTTP_AUTHORIZATION': authorization_header} if authorization_header else {}
