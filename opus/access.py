"""Visibility rules for public and private works."""

from django.db.models import Q
from rest_framework.permissions import SAFE_METHODS, BasePermission


def visible_to_user(queryset, user, work_path=""):
    """Limit a queryset to public works or private works owned by ``user``."""

    return queryset.filter(
        Q(**{f"{work_path}is_private": False}) | Q(**{f"{work_path}owner": user})
    )


def can_access_work(work, user):
    return not work.is_private or work.owner_id == user.pk


def owns_work(work, user):
    return work.owner_id == user.pk


def can_edit_lexical_entry(entry, user):
    """Owners and curators edit an entry.

    An entry from before entries had owners may be edited by the one user whose
    annotations use it, which lets them claim it.
    """

    if user.is_staff or entry.owner_id == user.pk:
        return True
    if entry.owner_id is not None:
        return False
    return (
        entry.annotations.filter(user=user).exists()
        and not entry.annotations.exclude(user=user).exists()
    )


class CuratorWritePermission(BasePermission):
    """Keep shared catalog data readable while reserving changes for curators."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.method in SAFE_METHODS or request.user.is_staff)
        )
