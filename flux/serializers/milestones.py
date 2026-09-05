"""Milestone serialization."""

from django.db import models
from rest_framework import serializers

from flux.models import Milestone, Project, Tag


class MilestoneSerializer(serializers.ModelSerializer):
    update_count = serializers.IntegerField(source="updates.count", read_only=True)

    class Meta:
        model = Milestone
        fields = ["id", "project", "title", "description", "status", "target_date", "created_at", "updated_at", "files", "tags", "update_count"]
        read_only_fields = ["created_at", "updated_at"]

    def validate_project(self, project):
        request = self.context["request"]
        if not project.members.filter(pk=request.user.pk).exists():
            raise serializers.ValidationError("You must be a member of this project.")
        return project

    def validate_tags(self, tags):
        project = self.instance.project if self.instance is not None else self.initial_data.get("project")
        if self.instance is None:
            try:
                project = Project.objects.get(pk=project)
            except (Project.DoesNotExist, TypeError, ValueError) as exc:
                raise serializers.ValidationError("A valid project is required.") from exc
        request = self.context["request"]
        allowed_ids = Tag.objects.filter(models.Q(created_by=request.user) | models.Q(projects=project) | models.Q(milestones__project=project)).values_list("pk", flat=True)
        if any(tag.pk not in allowed_ids for tag in tags):
            raise serializers.ValidationError("Tags must be available in this project or created by you.")
        return tags
