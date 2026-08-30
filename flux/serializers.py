from rest_framework import serializers

from flux.models import Milestone, Project, Task, Update


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
            'files',
        ]
        read_only_fields = ['created_at', 'updated_at']


class MilestoneSerializer(serializers.ModelSerializer):
    update_count = serializers.IntegerField(source='updates.count', read_only=True)
    class Meta:
        model = Milestone
        fields = [
            'id',
            'project',
            'title',
            'description',
            'status',
            'target_date',
            'created_at',
            'updated_at',
            'files',
            'update_count'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def validate_project(self, project):
        request = self.context['request']
        if not project.members.filter(pk=request.user.pk).exists():
            raise serializers.ValidationError("You must be a member of this project.")
        return project


class TaskSerializer(serializers.ModelSerializer):
    update_count = serializers.IntegerField(source='updates.count', read_only=True)
    class Meta:
        model = Task
        fields = [
            'id',
            'project',
            'milestone',
            'parent',
            'subtasks',
            'requirements',
            'required_by',
            'assignees',
            'title',
            'description',
            'due_date',
            'recurrence',
            'recurrence_interval',
            'recurrence_end_date',
            'recurrence_source',
            'priority',
            'status',
            'created_at',
            'updated_at',
            'files',
            'update_count'
        ]
        read_only_fields = [
            'subtasks',
            'required_by',
            'recurrence_source',
            'created_at',
            'updated_at',
        ]

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

        milestone = attrs.get('milestone', getattr(self.instance, 'milestone', None))
        if milestone is not None and milestone.project_id != project.pk:
            raise serializers.ValidationError(
                {'milestone': "Milestone must belong to the same project."}
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

        recurrence = attrs.get('recurrence', getattr(self.instance, 'recurrence', Task.Recurrence.NONE))
        due_date = attrs.get('due_date', getattr(self.instance, 'due_date', None))
        recurrence_interval = attrs.get(
            'recurrence_interval',
            getattr(self.instance, 'recurrence_interval', 1),
        )
        recurrence_end_date = attrs.get(
            'recurrence_end_date',
            getattr(self.instance, 'recurrence_end_date', None),
        )
        if recurrence != Task.Recurrence.NONE and due_date is None:
            raise serializers.ValidationError(
                {'due_date': "Recurring tasks must have a due date."}
            )
        if recurrence_interval < 1:
            raise serializers.ValidationError(
                {'recurrence_interval': "Recurrence interval must be at least 1."}
            )
        if recurrence_end_date is not None and due_date is not None and recurrence_end_date < due_date:
            raise serializers.ValidationError(
                {'recurrence_end_date': "Recurrence end date cannot be before the due date."}
            )

        return attrs


class UpdateSerializer(serializers.ModelSerializer):
    
    class Meta:
        model = Update
        fields = [
            'id',
            'project',
            'milestone',
            'task',
            'author',
            'content',
            'created_at',
            'updated_at',
            'files'
        ]
        read_only_fields = ['author', 'created_at', 'updated_at']

    def validate_project(self, project):
        request = self.context['request']
        if not project.members.filter(pk=request.user.pk).exists():
            raise serializers.ValidationError("You must be a member of this project.")
        return project

    def validate(self, attrs):
        project = attrs.get('project') or getattr(self.instance, 'project', None)

        milestone = attrs.get('milestone', getattr(self.instance, 'milestone', None))
        if milestone is not None and milestone.project_id != project.pk:
            raise serializers.ValidationError(
                {'milestone': "Milestone must belong to the same project."}
            )

        task = attrs.get('task', getattr(self.instance, 'task', None))
        if task is not None and task.project_id != project.pk:
            raise serializers.ValidationError(
                {'task': "Task must belong to the same project."}
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
