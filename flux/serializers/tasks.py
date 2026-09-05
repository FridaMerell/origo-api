"""Project-task serialization and dependency validation."""

from rest_framework import serializers

from flux.models import Task


class TaskSerializer(serializers.ModelSerializer):
    update_count = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Task
        fields = ["id", "project", "milestone", "parent", "subtasks", "requirements", "required_by", "assignees", "title", "description", "due_date", "recurrence", "recurrence_interval", "recurrence_end_date", "recurrence_source", "priority", "status", "created_at", "updated_at", "files", "update_count"]
        read_only_fields = ["subtasks", "required_by", "recurrence_source", "created_at", "updated_at"]

    def validate_project(self, project):
        if not project.members.filter(pk=self.context["request"].user.pk).exists():
            raise serializers.ValidationError("You must be a member of this project.")
        return project

    def get_update_count(self, task):
        """Use the queryset annotation when available instead of loading updates."""
        update_count = getattr(task, "update_count", None)
        return task.updates.count() if update_count is None else update_count

    def validate_parent(self, parent):
        if parent is None or self.instance is None:
            return parent
        parent_ids = dict(
            Task.objects.filter(project_id=self.instance.project_id).values_list(
                'pk', 'parent_id'
            )
        )
        ancestor_id = parent.pk
        while ancestor_id is not None:
            if ancestor_id == self.instance.pk:
                raise serializers.ValidationError("This would create a circular subtask chain.")
            ancestor_id = parent_ids.get(ancestor_id)
        return parent

    def validate_requirements(self, requirements):
        if self.instance is None:
            return requirements
        graph = _requirement_graph(self.instance.project_id)
        for candidate in requirements:
            if candidate.pk == self.instance.pk:
                raise serializers.ValidationError("A task cannot require itself.")
            if _requires(candidate.pk, self.instance.pk, graph):
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
        if assignees is not None:
            assignee_ids = {user.pk for user in assignees}
            member_ids = set(
                project.members.filter(pk__in=assignee_ids).values_list('pk', flat=True)
            )
            if member_ids != assignee_ids:
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


def _requirement_graph(project_id):
    """Load one project's complete dependency graph with one query."""
    graph = {}
    edges = Task.objects.filter(project_id=project_id).values_list(
        'pk', 'requirements__pk'
    )
    for task_id, requirement_id in edges:
        if requirement_id is not None:
            graph.setdefault(task_id, set()).add(requirement_id)
    return graph


def _requires(task_id, target_id, graph):
    """Whether one task requires another, directly or transitively."""
    pending = [task_id]
    visited = set()
    while pending:
        current_id = pending.pop()
        for requirement_id in graph.get(current_id, ()):
            if requirement_id == target_id:
                return True
            if requirement_id not in visited:
                visited.add(requirement_id)
                pending.append(requirement_id)
    return False
