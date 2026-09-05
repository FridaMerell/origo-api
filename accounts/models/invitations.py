"""Multi-use account and membership invitations."""

import secrets
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models
from django.utils import timezone

from ._revocable import RevocableHashedTokenMixin

# Distinguishes an omitted expiry (use the default) from an explicit ``None``.
_UNSET = object()


class Invitation(RevocableHashedTokenMixin, models.Model):
    """A live link that grants an account, house membership, or project membership."""

    DEFAULT_TTL = timedelta(days=7)

    house = models.ForeignKey("verso.House", on_delete=models.CASCADE, related_name="invitations", null=True, blank=True)
    project = models.ForeignKey("flux.Project", on_delete=models.CASCADE, related_name="invitations", null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="invitations_created")
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
                condition=models.Q(house__isnull=True) | models.Q(project__isnull=True),
            )
        ]

    def __str__(self):
        state = "active" if self.is_active else "inactive"
        return f"Invitation to {self.target or 'a new account'} ({state})"

    @property
    def target(self):
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
            raise DjangoValidationError("An invitation can target at most one of house or project.")

    @classmethod
    def issue(cls, *, house=None, project=None, created_by=None, label="", expires_at=_UNSET):
        if house and project:
            raise ValueError("Pass at most one of house or project.")
        plaintext_token = secrets.token_urlsafe(32)
        if expires_at is _UNSET:
            expires_at = timezone.now() + cls.DEFAULT_TTL
        invitation = cls.objects.create(
            house=house, project=project, created_by=created_by, label=label,
            token_hash=cls.hash_value(plaintext_token), expires_at=expires_at,
        )
        return invitation, plaintext_token

    @classmethod
    def resolve(cls, plaintext_token):
        try:
            invitation = cls.objects.select_related("house", "project").get(token_hash=cls.hash_value(plaintext_token))
        except cls.DoesNotExist:
            return None
        return invitation if invitation.is_active else None

    def redeem(self, user):
        if self.target is not None:
            self.target.members.add(user)
        self.uses = models.F("uses") + 1
        self.last_used_at = timezone.now()
        self.save(update_fields=["uses", "last_used_at"])
        self.refresh_from_db(fields=["uses"])
