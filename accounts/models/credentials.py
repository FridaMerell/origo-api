"""Revocable credentials used by narrowly scoped Codex integrations."""

import secrets

from django.db import models
from django.utils import timezone

from ._revocable import RevocableHashedTokenMixin
from .identity import User


class CodexToken(RevocableHashedTokenMixin, models.Model):
    """A per-user credential whose plaintext value is returned only on issue."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="codex_tokens")
    label = models.CharField(max_length=100, default="Codex")
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.label} token for {self.user}"

    @classmethod
    def issue(cls, user, *, label="Codex", expires_at=None):
        plaintext_token = secrets.token_urlsafe(32)
        token = cls.objects.create(
            user=user, label=label, token_hash=cls.hash_value(plaintext_token), expires_at=expires_at
        )
        return token, plaintext_token

    @classmethod
    def authenticate(cls, plaintext_token):
        try:
            token = cls.objects.select_related("user").get(token_hash=cls.hash_value(plaintext_token))
        except cls.DoesNotExist:
            return None
        if not token.is_active:
            return None
        token.last_used_at = timezone.now()
        token.save(update_fields=["last_used_at"])
        return token
