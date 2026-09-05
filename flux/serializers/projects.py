"""Project serialization."""

from django.db.models import Q
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
            submitted_ids = {tag.pk for tag in tags}
            allowed_ids = set(
                self.instance.tags.model.objects.filter(pk__in=submitted_ids)
                .filter(
                    Q(created_by=request.user)
                    | Q(projects=self.instance)
                    | Q(milestones__project=self.instance)
                )
                .values_list('pk', flat=True)
                .distinct()
            )
            disallowed = [tag for tag in tags if tag.pk not in allowed_ids]
        if disallowed:
            raise serializers.ValidationError("Tags must be created by you before they can be added to a project.")
        return tags
