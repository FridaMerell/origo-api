"""Flux views, organised by domain to match ``flux.serializers``."""

from .codex import (
    CodexIdentityListView,
    CodexProjectDocumentUpdateView,
    CodexProjectPlanAppendView,
    CodexProjectPlanDetailView,
    CodexProjectPlanListView,
    CodexProjectMilestoneStatusView,
    CodexProjectScaffoldView,
    CodexProjectTaskCreateView,
    CodexProjectTaskStatusView,
)
from .datamodel import EntityViewSet, FieldViewSet, RelationViewSet
from .design import (
    IntegrationViewSet,
    ResourceViewSet,
    RolePermissionViewSet,
    RoleViewSet,
    ScreenViewSet,
    SeedRowViewSet,
    StackProfileViewSet,
)
from .documents import DocumentViewSet
from .identity import VisualProfileViewSet
from .milestones import MilestoneViewSet
from .projects import ProjectViewSet
from .tags import TagViewSet
from .tasks import TaskViewSet
from .timeline import TimelineView
from .updates import UpdateViewSet

__all__ = [
    "CodexIdentityListView",
    "CodexProjectDocumentUpdateView",
    "CodexProjectPlanAppendView",
    "CodexProjectPlanDetailView",
    "CodexProjectPlanListView",
    "CodexProjectMilestoneStatusView",
    "CodexProjectScaffoldView",
    "CodexProjectTaskCreateView",
    "CodexProjectTaskStatusView",
    "DocumentViewSet",
    "EntityViewSet",
    "FieldViewSet",
    "IntegrationViewSet",
    "MilestoneViewSet",
    "ProjectViewSet",
    "RelationViewSet",
    "ResourceViewSet",
    "RolePermissionViewSet",
    "RoleViewSet",
    "ScreenViewSet",
    "SeedRowViewSet",
    "StackProfileViewSet",
    "TagViewSet",
    "TaskViewSet",
    "TimelineView",
    "UpdateViewSet",
    "VisualProfileViewSet",
]
