"""Flux views, organised by domain to match ``flux.serializers``."""

from .codex import (
    CodexProjectDocumentUpdateView,
    CodexProjectPlanAppendView,
    CodexProjectPlanDetailView,
    CodexProjectPlanListView,
    CodexProjectTaskCreateView,
)
from .documents import DocumentViewSet
from .milestones import MilestoneViewSet
from .projects import ProjectViewSet
from .tags import TagViewSet
from .tasks import TaskViewSet
from .timeline import TimelineView
from .updates import UpdateViewSet

__all__ = [
    "CodexProjectDocumentUpdateView",
    "CodexProjectPlanAppendView",
    "CodexProjectPlanDetailView",
    "CodexProjectPlanListView",
    "CodexProjectTaskCreateView",
    "DocumentViewSet",
    "MilestoneViewSet",
    "ProjectViewSet",
    "TagViewSet",
    "TaskViewSet",
    "TimelineView",
    "UpdateViewSet",
]
