"""Progress updates linked to a project, milestone, or task."""

from django.conf import settings
from django.db import models

from .planning import Milestone, Project
from .tasks import Task


class Update(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="updates")
    milestone = models.ForeignKey(Milestone, on_delete=models.CASCADE, null=True, blank=True, related_name="updates")
    task = models.ForeignKey(Task, on_delete=models.CASCADE, null=True, blank=True, related_name="updates")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="updates")
    content = models.TextField()
    files = models.JSONField(blank=True, default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Update on {self.project} at {self.created_at}"
