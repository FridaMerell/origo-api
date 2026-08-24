from rest_framework import serializers

from flux.models import Project, Task


class ProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = [
            'id',
            'name',
            'description',
            'members',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']


class TaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = [
            'id',
            'project',
            'parent',
            'subtasks',
            'requirements',
            'required_by',
            'assignees',
            'title',
            'description',
            'due_date',
            'priority',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['subtasks', 'required_by', 'created_at', 'updated_at']

    def validate_project(self, project):
        request = self.context['request']
        if not project.members.filter(pk=request.user.pk).exists():
            raise serializers.ValidationError("You must be a member of this project.")
        return project

    def validate_parent(self, parent):
        if parent is None or self.instance is None:
            return parent
        ancestor = parent
        while ancestor is not None:
            if ancestor.pk == self.instance.pk:
                raise serializers.ValidationError(
                    "This would create a circular subtask chain."
                )
            ancestor = ancestor.parent
        return parent

    def validate_requirements(self, requirements):
        if self.instance is None:
            return requirements
        for candidate in requirements:
            if candidate.pk == self.instance.pk:
                raise serializers.ValidationError("A task cannot require itself.")
            if _requires(candidate, self.instance):
                raise serializers.ValidationError(
                    f'"{candidate}" already (directly or indirectly) requires this '
                    "task, so adding it here would create a circular dependency."
                )
        return requirements

    def validate(self, attrs):
        project = attrs.get('project') or getattr(self.instance, 'project', None)

        parent = attrs.get('parent', getattr(self.instance, 'parent', None))
        if parent is not None and parent.project_id != project.pk:
            raise serializers.ValidationError(
                {'parent': "Parent task must belong to the same project."}
            )

        requirements = attrs.get('requirements')
        if requirements is not None:
            mismatched = [r for r in requirements if r.project_id != project.pk]
            if mismatched:
                raise serializers.ValidationError(
                    {'requirements': "Requirements must belong to the same project."}
                )

        assignees = attrs.get('assignees')
        if assignees is not None:
            non_members = [u for u in assignees if not project.members.filter(pk=u.pk).exists()]
            if non_members:
                raise serializers.ValidationError(
                    {'assignees': "Assignees must be members of the project."}
                )

        return attrs


def _requires(task, target, visited=None):
    """Whether `task` requires `target`, directly or transitively."""
    if visited is None:
        visited = set()
    for requirement in task.requirements.all():
        if requirement.pk == target.pk:
            return True
        if requirement.pk in visited:
            continue
        visited.add(requirement.pk)
        if _requires(requirement, target, visited):
            return True
    return False
