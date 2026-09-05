"""Flux views, organised by domain to match ``flux.serializers``."""

from .codex import (
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
from .updates import UpdateViewSet

__all__ = [
    "CodexProjectPlanAppendView",
    "CodexProjectPlanDetailView",
    "CodexProjectPlanListView",
    "CodexProjectTaskCreateView",
    "DocumentViewSet",
    "MilestoneViewSet",
    "ProjectViewSet",
    "TagViewSet",
    "TaskViewSet",
    "UpdateViewSet",
]
