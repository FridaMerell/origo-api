"""Shared behavior for hashed, revocable, optionally-expiring credentials."""

import hashlib

from django.utils import timezone


class RevocableHashedTokenMixin:
    """Plain mixin (not a Django abstract model -- no fields, no migration impact).

    Expects the including model to define ``token_hash``, ``expires_at`` and
    ``revoked_at`` fields matching :class:`accounts.models.CodexToken` /
    :class:`accounts.models.Invitation`.
    """

    @staticmethod
    def hash_value(plaintext_token):
        return hashlib.sha256(plaintext_token.encode("utf-8")).hexdigest()

    @property
    def is_active(self):
        return self.revoked_at is None and (self.expires_at is None or self.expires_at > timezone.now())

    def revoke(self):
        if self.revoked_at is None:
            self.revoked_at = timezone.now()
            self.save(update_fields=["revoked_at"])
