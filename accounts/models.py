import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models
from django.utils import timezone

# Sentinel so ``Invitation.issue`` can tell "caller passed expires_at=None"
# (meaning: never expires) apart from "caller said nothing" (use the default TTL).
_UNSET = object()


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


class Invitation(models.Model):
    """A shareable, multi-use invite link.

    At most one target is set: a Verso ``house`` or a Flux ``project``. With no
    target the invitation only grants an account. The token plaintext is
    returned only once, from ``issue``; only its hash is stored. Anyone holding
    a live token (not revoked, not past ``expires_at``) can redeem it -- either
    as an existing user or by creating an account in the same request -- and is
    added to the target group if there is one. Redeeming does not consume the
    invitation; it stays usable until it expires or is revoked.
    """

    DEFAULT_TTL = timedelta(days=7)

    house = models.ForeignKey(
        "verso.House",
        on_delete=models.CASCADE,
        related_name="invitations",
        null=True,
        blank=True,
    )
    project = models.ForeignKey(
        "flux.Project",
        on_delete=models.CASCADE,
        related_name="invitations",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invitations_created",
    )
    label = models.CharField(max_length=100, blank=True)
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    uses = models.PositiveIntegerField(default=0)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                name="invitation_at_most_one_target",
                condition=(
                    models.Q(house__isnull=True) | models.Q(project__isnull=True)
                ),
            ),
        ]

    def __str__(self):
        state = "active" if self.is_active else "inactive"
        return f"Invitation to {self.target or 'a new account'} ({state})"

    @property
    def target(self):
        """The group this invitation adds redeemers to, or ``None``."""
        return self.house or self.project

    @property
    def target_kind(self):
        if self.house_id:
            return "house"
        if self.project_id:
            return "project"
        return "account"

    def clean(self):
        if self.house_id and self.project_id:
            raise DjangoValidationError(
                "An invitation can target at most one of house or project."
            )

    @classmethod
    def issue(
        cls, *, house=None, project=None, created_by=None, label="",
        expires_at=_UNSET,
    ):
        """Create an invitation and return ``(instance, plaintext_token)`` once."""
        if house and project:
            raise ValueError("Pass at most one of house or project.")
        plaintext_token = secrets.token_urlsafe(32)
        if expires_at is _UNSET:
            expires_at = timezone.now() + cls.DEFAULT_TTL
        invitation = cls.objects.create(
            house=house,
            project=project,
            created_by=created_by,
            label=label,
            token_hash=cls.hash_value(plaintext_token),
            expires_at=expires_at,
        )
        return invitation, plaintext_token

    @staticmethod
    def hash_value(plaintext_token):
        return hashlib.sha256(plaintext_token.encode("utf-8")).hexdigest()

    @classmethod
    def resolve(cls, plaintext_token):
        """Return the live invitation for a plaintext token, or ``None``."""
        try:
            invitation = cls.objects.select_related("house", "project").get(
                token_hash=cls.hash_value(plaintext_token)
            )
        except cls.DoesNotExist:
            return None
        return invitation if invitation.is_active else None

    @property
    def is_active(self):
        return self.revoked_at is None and (
            self.expires_at is None or self.expires_at > timezone.now()
        )

    def redeem(self, user):
        """Add ``user`` to the target group (if any) and record the redemption."""
        if self.target is not None:
            self.target.members.add(user)
        self.uses = models.F("uses") + 1
        self.last_used_at = timezone.now()
        self.save(update_fields=["uses", "last_used_at"])
        self.refresh_from_db(fields=["uses"])

    def revoke(self):
        if self.revoked_at is None:
            self.revoked_at = timezone.now()
            self.save(update_fields=["revoked_at"])
