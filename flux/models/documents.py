"""Labels and documentation stored with Flux work."""

from django.conf import settings
from django.db import models

from .planning import Milestone, Project


class Tag(models.Model):
    """A reusable label which can be applied to projects and milestones."""

    name = models.CharField(max_length=80)
    color = models.CharField(max_length=7, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="flux_tags")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["created_by", "name"], name="flux_tag_unique_name_per_creator")]
        ordering = ["name"]

    def __str__(self):
        return self.name


class Document(models.Model):
    """Markdown documentation and Mermaid diagrams belonging to a project."""

    class Kind(models.TextChoices):
        MARKDOWN = "markdown", "Markdown"
        FLOWCHART = "flowchart", "Flowchart"
        DATABASE_SCHEMA = "database_schema", "Database schema"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="documents")
    milestone = models.ForeignKey(Milestone, on_delete=models.CASCADE, null=True, blank=True, related_name="documents")
    task = models.ForeignKey("Task", on_delete=models.CASCADE, null=True, blank=True, related_name="documents")
    title = models.CharField(max_length=255)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.MARKDOWN)
    content = models.TextField(blank=True)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="flux_documents")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title
