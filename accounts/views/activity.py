"""The signed-in user's latest activity across all apps."""
from django.apps import apps
from rest_framework import permissions
from rest_framework.generics import GenericAPIView

from origo.pagination import StandardPagination

TITLE_MAX_LENGTH = 120

# (app label, model name, kind, field linking the row to the user,
#  timestamp field, field used as the title)
ACTIVITY_SOURCES = [
    ("tempus", "Observation", "observation", "user", "created_at", "species__swedish_name"),
    ("tempus", "Checklist", "checklist", "user", "created_at", "name"),
    ("tempus", "Route", "route", "user", "created_at", "name"),
    ("opus", "Bookmark", "bookmark", "user", "created_at", "title"),
    ("opus", "Excerpt", "excerpt", "user", "created_at", "title"),
    ("opus", "Annotation", "annotation", "user", "created_at", "body"),
    ("verso", "Photo", "photo", "author", "created_at", "title"),
    ("verso", "Drawing", "drawing", "author", "created_at", "name"),
    ("verso", "Document", "document", "author", "created_at", "title"),
    ("verso", "HistoryEvent", "history_event", "author", "created_at", "title"),
    ("verso", "VersoUpdate", "update", "author", "created_at", "title"),
    ("flux", "Update", "update", "author", "created_at", "content"),
    ("flux", "Document", "document", "author", "created_at", "title"),
    ("apsis", "Post", "post", "author", "created_at", "content"),
]


class ActivityFeed:
    """Lazy, sliceable union of the user's rows from every activity source.

    Each source is queried for at most the rows needed to fill the requested
    slice, so a page deep into the feed never loads whole tables.
    """

    def __init__(self, user):
        self.sources = []
        for app_label, model_name, kind, user_field, time_field, title_field in ACTIVITY_SOURCES:
            model = apps.get_model(app_label, model_name)
            queryset = model.objects.filter(**{user_field: user})
            self.sources.append((app_label, kind, queryset, time_field, title_field))

    def __len__(self):
        return sum(queryset.count() for _, _, queryset, _, _ in self.sources)

    def __getitem__(self, key):
        if not isinstance(key, slice):
            raise TypeError("ActivityFeed only supports slicing.")
        start = key.start or 0
        stop = key.stop
        rows = []
        for app_label, kind, queryset, time_field, title_field in self.sources:
            ordered = queryset.order_by(f"-{time_field}", "-pk").values_list(
                "pk", time_field, title_field
            )
            for pk, occurred_at, title in ordered[:stop]:
                rows.append(
                    {
                        "app": app_label,
                        "kind": kind,
                        "id": str(pk),
                        "title": (title or "")[:TITLE_MAX_LENGTH],
                        "occurred_at": occurred_at,
                    }
                )
        rows.sort(
            key=lambda row: (row["occurred_at"], row["app"], row["kind"], row["id"]),
            reverse=True,
        )
        return rows[start:stop]


class ActivityView(GenericAPIView):
    """``GET /api/accounts/activity/``: newest-first activity across all apps."""

    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination

    def get(self, request):
        page = self.paginate_queryset(ActivityFeed(request.user))
        return self.get_paginated_response(page)
