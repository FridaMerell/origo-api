"""Visibility rules for public and private works."""

from django.db.models import BooleanField, Exists, ExpressionWrapper, OuterRef, Q, Value
from rest_framework.permissions import SAFE_METHODS, BasePermission


def visible_to_user(queryset, user, work_path=""):
    """Limit a queryset to public works or private works owned by ``user``."""

    return queryset.filter(
        Q(**{f"{work_path}is_private": False}) | Q(**{f"{work_path}owner": user})
    )


def visible_entry_filter(user, entry_path=""):
    """Entries the user owns, unowned catalog entries, and entries in glossaries the user can see.

    The glossaries are a subquery, so the condition never repeats a row and needs no ``distinct()``.
    """

    # Imported here: the models do not know about access rules.
    from opus.models import Glossary

    in_visible_glossary = Exists(
        visible_to_user(Glossary.objects.filter(entries=OuterRef(f"{entry_path}pk")), user)
    )
    return (
        Q(**{f"{entry_path}owner": user})
        | Q(**{f"{entry_path}owner__isnull": True})
        | Q(in_visible_glossary)
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


def own_entry_condition(user):
    """The user's own words, as a condition on entries.

    Those they own, and the unowned ones from before entries had owners that only their
    annotations use.
    """

    # Imported here: the models do not know about access rules.
    from opus.models import Annotation

    uses = Annotation.objects.filter(lexical_entry=OuterRef("pk"))
    return Q(owner=user) | Q(
        Exists(uses.filter(user=user)), ~Exists(uses.exclude(user=user)), owner__isnull=True
    )


def _editable_entry_condition(user):
    """``can_edit_lexical_entry`` as a condition on entries; None when the user may edit them all."""

    return None if user.is_staff else own_entry_condition(user)


def editable_lexical_entries(queryset, user):
    """Limit a queryset of entries to those ``can_edit_lexical_entry`` lets ``user`` edit."""

    condition = _editable_entry_condition(user)
    return queryset if condition is None else queryset.filter(condition)


def with_edit_permission(queryset, user):
    """Annotate each entry with ``request_can_edit``: what ``can_edit_lexical_entry`` would answer."""

    condition = _editable_entry_condition(user)
    return queryset.annotate(
        request_can_edit=(
            Value(True) if condition is None else ExpressionWrapper(condition, output_field=BooleanField())
        )
    )


class CuratorWritePermission(BasePermission):
    """Keep shared catalog data readable while reserving changes for curators."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.method in SAFE_METHODS or request.user.is_staff)
        )
