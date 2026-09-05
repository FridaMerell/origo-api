"""Project serialization."""

from rest_framework import serializers

from flux.models import Project


class ProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = ["id", "name", "description", "members", "created_at", "updated_at", "files", "tags"]
        read_only_fields = ["created_at", "updated_at"]

    def validate_tags(self, tags):
        request = self.context["request"]
        if self.instance is None:
            disallowed = [tag for tag in tags if tag.created_by_id != request.user.pk]
        else:
            disallowed = [tag for tag in tags if tag.created_by_id != request.user.pk and not self.instance.tags.filter(pk=tag.pk).exists() and not tag.milestones.filter(project=self.instance).exists()]
        if disallowed:
            raise serializers.ValidationError("Tags must be created by you before they can be added to a project.")
        return tags
