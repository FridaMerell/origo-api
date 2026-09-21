"""Visibility rules for public and private works."""

from django.db.models import Q


def visible_to_user(queryset, user, work_path=""):
    """Limit a queryset to public works or private works owned by ``user``."""

    return queryset.filter(
        Q(**{f"{work_path}is_private": False}) | Q(**{f"{work_path}owner": user})
    )


def can_access_work(work, user):
    return not work.is_private or work.owner_id == user.pk
