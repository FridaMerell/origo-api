"""Serializers organized by domain."""

from .documents import DocumentSerializer
from .milestones import MilestoneSerializer
from .projects import ProjectSerializer
from .tags import TagSerializer
from .tasks import TaskSerializer
from .updates import UpdateSerializer

__all__ = ["DocumentSerializer", "MilestoneSerializer", "ProjectSerializer", "TagSerializer", "TaskSerializer", "UpdateSerializer"]
