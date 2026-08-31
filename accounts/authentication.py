from rest_framework import authentication, exceptions

from accounts.models import CodexToken


class CodexTokenAuthentication(authentication.BaseAuthentication):
    """Authenticate the dedicated, user-owned Codex API credential."""

    keyword = b'codex'

    def authenticate(self, request):
        authorization = authentication.get_authorization_header(request).split()
        if not authorization:
            return None
        if authorization[0].lower() != self.keyword:
            return None
        if len(authorization) != 2:
            raise exceptions.AuthenticationFailed(
                'Authorization must use the Codex token scheme.'
            )
        try:
            plaintext_token = authorization[1].decode('ascii')
        except UnicodeError as exc:
            raise exceptions.AuthenticationFailed('Invalid Codex token.') from exc

        token = CodexToken.authenticate(plaintext_token)
        if token is None:
            raise exceptions.AuthenticationFailed('Invalid, expired, or revoked Codex token.')
        return (token.user, token)

    def authenticate_header(self, request):
        return 'Codex'
