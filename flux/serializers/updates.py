"""Project-update serialization."""

from rest_framework import serializers

from flux.models import Update


class UpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Update
        fields = ["id", "project", "milestone", "task", "author", "content", "created_at", "updated_at", "files"]
        read_only_fields = ["author", "created_at", "updated_at"]

    def validate_project(self, project):
        if not project.members.filter(pk=self.context["request"].user.pk).exists():
            raise serializers.ValidationError("You must be a member of this project.")
        return project

    def validate(self, attrs):
        project = attrs.get("project") or getattr(self.instance, "project", None)
        milestone = attrs.get("milestone", getattr(self.instance, "milestone", None))
        task = attrs.get("task", getattr(self.instance, "task", None))
        if milestone is not None and milestone.project_id != project.pk:
            raise serializers.ValidationError({"milestone": "Milestone must belong to the same project."})
        if task is not None and task.project_id != project.pk:
            raise serializers.ValidationError({"task": "Task must belong to the same project."})
        return attrs
