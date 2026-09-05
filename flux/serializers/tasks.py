"""Project-task serialization and dependency validation."""

from rest_framework import serializers

from flux.models import Task


class TaskSerializer(serializers.ModelSerializer):
    update_count = serializers.IntegerField(source="updates.count", read_only=True)

    class Meta:
        model = Task
        fields = ["id", "project", "milestone", "parent", "subtasks", "requirements", "required_by", "assignees", "title", "description", "due_date", "recurrence", "recurrence_interval", "recurrence_end_date", "recurrence_source", "priority", "status", "created_at", "updated_at", "files", "update_count"]
        read_only_fields = ["subtasks", "required_by", "recurrence_source", "created_at", "updated_at"]

    def validate_project(self, project):
        if not project.members.filter(pk=self.context["request"].user.pk).exists():
            raise serializers.ValidationError("You must be a member of this project.")
        return project

    def validate_parent(self, parent):
        if parent is None or self.instance is None:
            return parent
        ancestor = parent
        while ancestor is not None:
            if ancestor.pk == self.instance.pk:
                raise serializers.ValidationError("This would create a circular subtask chain.")
            ancestor = ancestor.parent
        return parent

    def validate_requirements(self, requirements):
        if self.instance is None:
            return requirements
        for candidate in requirements:
            if candidate.pk == self.instance.pk:
                raise serializers.ValidationError("A task cannot require itself.")
            if _requires(candidate, self.instance):
                raise serializers.ValidationError(f'"{candidate}" already (directly or indirectly) requires this task, so adding it here would create a circular dependency.')
        return requirements

    def validate(self, attrs):
        project = attrs.get("project") or getattr(self.instance, "project", None)
        parent = attrs.get("parent", getattr(self.instance, "parent", None))
        milestone = attrs.get("milestone", getattr(self.instance, "milestone", None))
        requirements = attrs.get("requirements")
        assignees = attrs.get("assignees")
        if parent is not None and parent.project_id != project.pk:
            raise serializers.ValidationError({"parent": "Parent task must belong to the same project."})
        if milestone is not None and milestone.project_id != project.pk:
            raise serializers.ValidationError({"milestone": "Milestone must belong to the same project."})
        if requirements is not None and any(item.project_id != project.pk for item in requirements):
            raise serializers.ValidationError({"requirements": "Requirements must belong to the same project."})
        if assignees is not None and any(not project.members.filter(pk=user.pk).exists() for user in assignees):
            raise serializers.ValidationError({"assignees": "Assignees must be members of the project."})
        recurrence = attrs.get("recurrence", getattr(self.instance, "recurrence", Task.Recurrence.NONE))
        due_date = attrs.get("due_date", getattr(self.instance, "due_date", None))
        interval = attrs.get("recurrence_interval", getattr(self.instance, "recurrence_interval", 1))
        end_date = attrs.get("recurrence_end_date", getattr(self.instance, "recurrence_end_date", None))
        if recurrence != Task.Recurrence.NONE and due_date is None:
            raise serializers.ValidationError({"due_date": "Recurring tasks must have a due date."})
        if interval < 1:
            raise serializers.ValidationError({"recurrence_interval": "Recurrence interval must be at least 1."})
        if end_date is not None and due_date is not None and end_date < due_date:
            raise serializers.ValidationError({"recurrence_end_date": "Recurrence end date cannot be before the due date."})
        return attrs


def _requires(task, target, visited=None):
    """Whether ``task`` requires ``target``, directly or transitively."""
    visited = set() if visited is None else visited
    for requirement in task.requirements.all():
        if requirement.pk == target.pk:
            return True
        if requirement.pk not in visited:
            visited.add(requirement.pk)
            if _requires(requirement, target, visited):
                return True
    return False
