import hashlib
import secrets

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    pass


class CodexToken(models.Model):
    """A revocable per-user credential for Codex integrations.

    Token plaintext is returned only from ``issue`` and is never persisted.
    Individual applications, such as Flux, can later authorize a token for
    their narrow integration surface without owning the credential itself.
    """

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='codex_tokens',
    )
    label = models.CharField(max_length=100, default='Codex')
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.label} token for {self.user}'

    @classmethod
    def issue(cls, user, *, label='Codex', expires_at=None):
        """Create a token and return ``(instance, plaintext_token)`` once."""
        plaintext_token = secrets.token_urlsafe(32)
        token = cls.objects.create(
            user=user,
            label=label,
            token_hash=cls.hash_value(plaintext_token),
            expires_at=expires_at,
        )
        return token, plaintext_token

    @staticmethod
    def hash_value(plaintext_token):
        return hashlib.sha256(plaintext_token.encode('utf-8')).hexdigest()

    @classmethod
    def authenticate(cls, plaintext_token):
        """Return the active token for a plaintext credential, if any."""
        try:
            token = cls.objects.select_related('user').get(
                token_hash=cls.hash_value(plaintext_token)
            )
        except cls.DoesNotExist:
            return None
        if not token.is_active:
            return None
        token.last_used_at = timezone.now()
        token.save(update_fields=['last_used_at'])
        return token

    @property
    def is_active(self):
        return (
            self.revoked_at is None
            and (self.expires_at is None or self.expires_at > timezone.now())
        )

    def revoke(self):
        if self.revoked_at is None:
            self.revoked_at = timezone.now()
            self.save(update_fields=['revoked_at'])


class Notification(models.Model):
    DOMAIN_CHOICES = [
        ("verso", "Verso"),
        ("flux", "Flux"),
        ("tempus", "Tempus"),
    ]

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="notifications"
    )
    domain = models.CharField(max_length=20, choices=DOMAIN_CHOICES)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="sent_notifications"
    )

    def __str__(self):
        return f"[{self.domain}] Notification for {self.user}: {self.message}"
