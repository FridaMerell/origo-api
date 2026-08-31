"""Validation, import and export of the private Flux plan payload."""

from datetime import date

from django.db import transaction
from django.db.models import Count

from flux.models import Document, Milestone, Project, Task, Update


class CodexPlanError(ValueError):
    """An error that may safely be returned to an API or MCP caller."""


def _private_projects_for(user):
    return (
        Project.objects.filter(members=user)
        .annotate(member_count=Count('members'))
        .filter(member_count=1)
    )


def _text(value, field, *, required=False, maximum=255):
    if value is None and not required:
        return ''
    if not isinstance(value, str):
        raise CodexPlanError(f'{field} must be text.')
    value = value.strip()
    if required and not value:
        raise CodexPlanError(f'{field} is required.')
    if len(value) > maximum:
        raise CodexPlanError(f'{field} must be at most {maximum} characters.')
    return value


def _date(value, field):
    if value is None:
        return None
    if not isinstance(value, str):
        raise CodexPlanError(f'{field} must be an ISO date (YYYY-MM-DD).')
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CodexPlanError(f'{field} must be an ISO date (YYYY-MM-DD).') from exc


def _items(plan, field):
    value = plan.get(field, [])
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise CodexPlanError(f'{field} must be a list of objects.')
    return value


def _choice(item, field, choices, default):
    value = item.get(field, default)
    if value not in choices:
        raise CodexPlanError(f'{field} is invalid.')
    return value


def _ref(item, field):
    return _text(item.get(field), field, required=True, maximum=100)


def _optional_id(value, field):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CodexPlanError(f'{field} must be a positive integer or null.')
    return value


def _validate_parent_refs(parent_refs):
    for ref in parent_refs:
        seen = set()
        current = ref
        while parent_refs.get(current) is not None:
            if current in seen:
                raise CodexPlanError('Task parent_ref values must not form a cycle.')
            seen.add(current)
            current = parent_refs[current]
            if current not in parent_refs:
                raise CodexPlanError(f'Unknown parent_ref: {current}.')


def serialize_project(project):
    milestones = list(project.milestones.order_by('id'))
    tasks = list(project.tasks.select_related('milestone', 'parent').order_by('id'))
    return {
        'id': project.id,
        'name': project.name,
        'description': project.description,
        'milestones': [
            {
                'id': item.id,
                'title': item.title,
                'description': item.description,
                'status': item.status,
                'target_date': item.target_date.isoformat() if item.target_date else None,
            }
            for item in milestones
        ],
        'tasks': [
            {
                'id': item.id,
                'title': item.title,
                'description': item.description,
                'milestone_id': item.milestone_id,
                'parent_id': item.parent_id,
                'due_date': item.due_date.isoformat() if item.due_date else None,
                'priority': item.priority,
                'status': item.status,
            }
            for item in tasks
        ],
        'updates': [
            {
                'id': item.id,
                'content': item.content,
                'milestone_id': item.milestone_id,
                'task_id': item.task_id,
                'created_at': item.created_at.isoformat(),
            }
            for item in project.updates.select_related('milestone', 'task').order_by('id')
        ],
        'documents': [
            {
                'id': item.id,
                'title': item.title,
                'kind': item.kind,
                'content': item.content,
                'milestone_id': item.milestone_id,
                'task_id': item.task_id,
                'created_at': item.created_at.isoformat(),
                'updated_at': item.updated_at.isoformat(),
            }
            for item in project.documents.select_related('milestone', 'task').order_by('id')
        ],
    }


def import_project_plan_for_user(user, plan):
    if not isinstance(plan, dict):
        raise CodexPlanError('plan must be an object.')
    milestone_payloads = _items(plan, 'milestones')
    task_payloads = _items(plan, 'tasks')
    update_payloads = _items(plan, 'updates')
    document_payloads = _items(plan, 'documents')

    with transaction.atomic():
        project = Project.objects.create(
            name=_text(plan.get('name'), 'name', required=True),
            description=_text(plan.get('description'), 'description', maximum=10000),
        )
        project.members.add(user)

        milestones = {}
        for item in milestone_payloads:
            ref = _ref(item, 'ref')
            if ref in milestones:
                raise CodexPlanError(f'Duplicate milestone ref: {ref}.')
            milestones[ref] = Milestone.objects.create(
                project=project,
                title=_text(item.get('title'), 'milestone.title', required=True),
                description=_text(item.get('description'), 'milestone.description', maximum=10000),
                status=_choice(item, 'status', Milestone.Status.values, Milestone.Status.NOT_STARTED),
                target_date=_date(item.get('target_date'), 'milestone.target_date'),
            )

        tasks, parent_refs = {}, {}
        for item in task_payloads:
            ref = _ref(item, 'ref')
            if ref in tasks:
                raise CodexPlanError(f'Duplicate task ref: {ref}.')
            milestone_ref = item.get('milestone_ref')
            if milestone_ref is not None and milestone_ref not in milestones:
                raise CodexPlanError(f'Unknown milestone_ref: {milestone_ref}.')
            tasks[ref] = Task.objects.create(
                project=project,
                milestone=milestones.get(milestone_ref),
                title=_text(item.get('title'), 'task.title', required=True),
                description=_text(item.get('description'), 'task.description', maximum=10000),
                due_date=_date(item.get('due_date'), 'task.due_date'),
                priority=_choice(item, 'priority', Task.Priority.values, Task.Priority.MEDIUM),
                status=_choice(item, 'status', Task.Status.values, Task.Status.NOT_STARTED),
            )
            parent_refs[ref] = item.get('parent_ref')

        _validate_parent_refs(parent_refs)
        for ref, parent_ref in parent_refs.items():
            if parent_ref is not None:
                tasks[ref].parent = tasks[parent_ref]
                tasks[ref].save(update_fields=['parent'])

        for item in update_payloads:
            milestone_ref, task_ref = item.get('milestone_ref'), item.get('task_ref')
            if milestone_ref is not None and milestone_ref not in milestones:
                raise CodexPlanError(f'Unknown milestone_ref: {milestone_ref}.')
            if task_ref is not None and task_ref not in tasks:
                raise CodexPlanError(f'Unknown task_ref: {task_ref}.')
            Update.objects.create(
                project=project,
                milestone=milestones.get(milestone_ref),
                task=tasks.get(task_ref),
                author=user,
                content=_text(item.get('content'), 'update.content', required=True, maximum=10000),
            )

        for item in document_payloads:
            milestone_ref = item.get('milestone_ref')
            task_ref = item.get('task_ref')
            if milestone_ref is not None and milestone_ref not in milestones:
                raise CodexPlanError(f'Unknown milestone_ref: {milestone_ref}.')
            if task_ref is not None and task_ref not in tasks:
                raise CodexPlanError(f'Unknown task_ref: {task_ref}.')
            Document.objects.create(
                project=project,
                milestone=milestones.get(milestone_ref),
                task=tasks.get(task_ref),
                title=_text(item.get('title'), 'document.title', required=True),
                kind=_choice(item, 'kind', Document.Kind.values, Document.Kind.MARKDOWN),
                content=_text(item.get('content'), 'document.content', maximum=100000),
                author=user,
            )
    return serialize_project(project)


def list_private_project_plans_for_user(user):
    return [
        {'id': item.id, 'name': item.name, 'updated_at': item.updated_at.isoformat()}
        for item in _private_projects_for(user).order_by('-updated_at')
    ]


def get_private_project_plan_for_user(user, project_id):
    try:
        project = _private_projects_for(user).get(pk=project_id)
    except Project.DoesNotExist as exc:
        raise CodexPlanError('Project not found or is not private to this Codex user.') from exc
    return serialize_project(project)


def add_task_to_private_project(user, project_id, task_data):
    """Create one task in an existing private project owned by the user."""
    if not isinstance(task_data, dict):
        raise CodexPlanError('task must be an object.')
    try:
        project = _private_projects_for(user).get(pk=project_id)
    except Project.DoesNotExist as exc:
        raise CodexPlanError('Project not found or is not private to this Codex user.') from exc

    milestone_id = _optional_id(task_data.get('milestone_id'), 'milestone_id')
    parent_id = _optional_id(task_data.get('parent_id'), 'parent_id')
    milestone = None
    parent = None
    if milestone_id is not None:
        try:
            milestone = Milestone.objects.get(pk=milestone_id, project=project)
        except Milestone.DoesNotExist as exc:
            raise CodexPlanError('milestone_id must belong to this project.') from exc
    if parent_id is not None:
        try:
            parent = Task.objects.get(pk=parent_id, project=project)
        except Task.DoesNotExist as exc:
            raise CodexPlanError('parent_id must belong to this project.') from exc

    task = Task.objects.create(
        project=project,
        milestone=milestone,
        parent=parent,
        title=_text(task_data.get('title'), 'task.title', required=True),
        description=_text(task_data.get('description'), 'task.description', maximum=10000),
        due_date=_date(task_data.get('due_date'), 'task.due_date'),
        priority=_choice(task_data, 'priority', Task.Priority.values, Task.Priority.MEDIUM),
        status=_choice(task_data, 'status', Task.Status.values, Task.Status.NOT_STARTED),
    )
    return {
        'id': task.id,
        'project_id': project.id,
        'title': task.title,
        'description': task.description,
        'milestone_id': task.milestone_id,
        'parent_id': task.parent_id,
        'due_date': task.due_date.isoformat() if task.due_date else None,
        'priority': task.priority,
        'status': task.status,
        'created_at': task.created_at.isoformat(),
    }
