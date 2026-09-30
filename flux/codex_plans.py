"""Validation, import and export of the private Flux plan payload."""

from datetime import date

from django.db import transaction
from django.db.models import Count

from flux.models import (
    ApiOperation,
    ApiOperationResponse,
    ApiProjection,
    Document,
    Entity,
    Field,
    Integration,
    IntegrationOperation,
    Milestone,
    Provider,
    Project,
    Relation,
    Resource,
    Role,
    RolePermission,
    Screen,
    SeedRow,
    StackProfile,
    Task,
    Update,
    VisualProfile,
)
from flux.services.scaffold import ScaffoldError, generate_files
from flux.services.scaffold import identity as identity_rules
from flux.services.scaffold import integration as integration_rules
from flux.services.scaffold.spec import build_spec, entity_mapping_info, unknown_seed_keys


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


def _bool(item, field, default=False):
    value = item.get(field, default)
    if not isinstance(value, bool):
        raise CodexPlanError(f'{field} must be true or false.')
    return value


def _max_length(value, field):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CodexPlanError(f'{field} must be a positive integer or null.')
    return value


def _scalar_text(value, field, *, maximum=255):
    """Accept text, numbers and booleans for values that are stored as text (e.g. a field default)."""
    if isinstance(value, bool):
        value = 'true' if value else 'false'
    elif isinstance(value, (int, float)):
        value = str(value)
    return _text(value, field, maximum=maximum)


def _string_list(item, field, allowed=None):
    value = item.get(field, [])
    if not isinstance(value, list) or not all(isinstance(entry, str) for entry in value):
        raise CodexPlanError(f'{field} must be a list of strings.')
    if allowed is not None and set(value) - set(allowed):
        raise CodexPlanError(f'{field} contains an invalid value.')
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
    milestones = list(project.milestones.order_by('order', 'created_at', 'id'))
    tasks = list(project.tasks.order_by('id'))
    return {
        'id': project.id,
        'name': project.name,
        'description': project.description,
        'include_identity': project.include_identity,
        'identity_id': project.identity_id,
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
            for item in project.updates.order_by('id')
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
            for item in project.documents.order_by('id')
        ],
        'entities': [
            {
                'id': entity.id,
                'name': entity.name,
                'description': entity.description,
                'fields': [
                    {
                        'id': field.id,
                        'name': field.name,
                        'type': field.type,
                        'description': field.description,
                        'nullable': field.nullable,
                        'unique': field.unique,
                        'default': field.default,
                        'max_length': field.max_length,
                    }
                    for field in entity.fields.all()
                ],
            }
            for entity in project.entities.prefetch_related('fields').order_by('id')
        ],
        'relations': [
            {
                'id': item.id,
                'source_id': item.source_id,
                'target_id': item.target_id,
                'kind': item.kind,
                'name': item.name,
                'related_name': item.related_name,
                'on_delete': item.on_delete,
                'nullable': item.nullable,
                'description': item.description,
            }
            for item in Relation.objects.filter(source__project=project).order_by('id')
        ],
        'stack_profile': _serialize_stack_profile(project),
        'resources': [
            {
                'id': item.id,
                'entity_id': item.entity_id,
                'path': item.path,
                'title': item.title,
                'description': item.description,
            }
            for item in Resource.objects.filter(entity__project=project).order_by('id')
        ],
        'api_projections': [
            {
                'id': item.id,
                'project_id': item.project_id,
                'name': item.name,
                'schema': item.schema,
                'description': item.description,
            }
            for item in ApiProjection.objects.filter(project=project).order_by('id')
        ],
        'api_operations': [
            {'id': item.id, 'resource_id': item.resource_id, 'key': item.key, 'method': item.method,
             'path': item.path, 'title': item.title, 'description': item.description,
             'parameters': item.parameters, 'request_schema': item.request_schema, 'pagination': item.pagination,
             'responses': [{'id': response.id, 'status_code': response.status_code,
                            'description': response.description, 'projection_id': response.projection_id}
                           for response in item.responses.all()]}
            for item in ApiOperation.objects.filter(resource__entity__project=project).prefetch_related('responses').order_by('id')
        ],
        'providers': [
            {
                'id': item.id,
                'name': item.name,
                'description': item.description,
                'resource_ids': [resource.id for resource in item.resources.all()],
            }
            for item in project.providers.prefetch_related('resources').order_by('id')
        ],
        'roles': [
            {
                'id': role.id,
                'name': role.name,
                'description': role.description,
                'permissions': [
                    {'operation_id': p.api_operation_id, 'scope': p.scope}
                    for p in role.permissions.all()
                ],
            }
            for role in project.roles.prefetch_related('permissions').order_by('id')
        ],
        'screens': [
            {
                'id': screen.id,
                'name': screen.name,
                'route': screen.route,
                'description': screen.description,
                'entity_ids': [entity.id for entity in screen.entities.all()],
                'parent_id': screen.parent_id,
            }
            for screen in project.screens.prefetch_related('entities').order_by('id')
        ],
        'integrations': [
            {
                'id': item.id,
                'name': item.name,
                'kind': item.kind,
                'description': item.description,
                'env_vars': item.env_vars,
                'base_url': item.base_url,
                'auth_type': item.auth_type,
                'auth_name': item.auth_name,
                'auth_env_var': item.auth_env_var,
                'auth_secret_env_var': item.auth_secret_env_var,
                'oauth_token_url': item.oauth_token_url,
                'timeout_seconds': item.timeout_seconds,
                'retries': item.retries,
                'rate_limit_per_minute': item.rate_limit_per_minute,
                'cache_ttl_seconds': item.cache_ttl_seconds,
                'operations': [
                    {
                        'id': op.id,
                        'name': op.name,
                        'description': op.description,
                        'method': op.method,
                        'path': op.path,
                        'body_format': op.body_format,
                        'params': op.params,
                        'items_path': op.items_path,
                        'pagination': op.pagination,
                        'pagination_config': op.pagination_config,
                        'filters': op.filters,
                        'entity_id': op.entity_id,
                        'key_field': op.key_field,
                        'mappings': op.mappings,
                        'sync': op.sync,
                        'sync_interval_minutes': op.sync_interval_minutes,
                        'cache_ttl_seconds': op.cache_ttl_seconds,
                        'sample_response': op.sample_response,
                    }
                    for op in item.operations.all()
                ],
            }
            for item in project.integrations.prefetch_related('operations').order_by('id')
        ],
        'seeds': [
            {'id': row.id, 'entity_id': row.entity_id, 'data': row.data, 'order': row.order}
            for row in SeedRow.objects.filter(entity__project=project).order_by('id')
        ],
    }


def _serialize_stack_profile(project):
    try:
        stack = project.stack_profile
    except StackProfile.DoesNotExist:
        return None
    return {
        'targets': stack.targets,
        'api_naming': stack.api_naming,
        'auth_method': stack.auth_method,
        'database': stack.database,
        'app_label': stack.app_label,
        'namespace': stack.namespace,
    }


def _append_plan_to_project(project, user, plan):
    if not isinstance(plan, dict):
        raise CodexPlanError('plan must be an object.')
    milestone_payloads = _items(plan, 'milestones')
    task_payloads = _items(plan, 'tasks')
    update_payloads = _items(plan, 'updates')
    document_payloads = _items(plan, 'documents')
    entity_payloads = _items(plan, 'entities')
    relation_payloads = _items(plan, 'relations')

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
    tasks_with_parents = []
    for ref, parent_ref in parent_refs.items():
        if parent_ref is not None:
            tasks[ref].parent = tasks[parent_ref]
            tasks_with_parents.append(tasks[ref])
    if tasks_with_parents:
        Task.objects.bulk_update(tasks_with_parents, ['parent'])

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

    entities = {}
    for item in entity_payloads:
        ref = _ref(item, 'ref')
        if ref in entities:
            raise CodexPlanError(f'Duplicate entity ref: {ref}.')
        entity_name = _text(item.get('name'), 'entity.name', required=True, maximum=100)
        if project.entities.filter(name=entity_name).exists() or any(e.name == entity_name for e in entities.values()):
            raise CodexPlanError(f'Entity name already exists in this project: {entity_name}.')
        entities[ref] = Entity.objects.create(
            project=project,
            name=entity_name,
            description=_text(item.get('description'), 'entity.description', maximum=10000),
        )
        field_payloads = _items(item, 'fields')
        field_names = set()
        for order, field_item in enumerate(field_payloads):
            field_name = _text(field_item.get('name'), 'field.name', required=True, maximum=100)
            if field_name in field_names:
                raise CodexPlanError(f'Duplicate field name in {entity_name}: {field_name}.')
            field_names.add(field_name)
            Field.objects.create(
                entity=entities[ref],
                name=field_name,
                type=_choice(field_item, 'type', Field.Type.values, Field.Type.STRING),
                description=_text(field_item.get('description'), 'field.description', maximum=10000),
                nullable=_bool(field_item, 'nullable'),
                unique=_bool(field_item, 'unique'),
                default=_scalar_text(field_item.get('default'), 'field.default'),
                max_length=_max_length(field_item.get('max_length'), 'field.max_length'),
                order=order,
            )

    relation_names = set()

    def resolve_relation_entity(ref, field):
        """Resolve a relation endpoint from this payload or an existing entity.

        Plan fragments commonly add relations after the entities already exist.
        Accepting an existing entity name makes those fragments appendable without
        duplicating the entity definitions.
        """
        if ref in entities:
            return entities[ref]
        if not isinstance(ref, str) or not ref.strip():
            raise CodexPlanError(f'{field} is required.')
        try:
            return project.entities.get(name=ref)
        except Entity.DoesNotExist as exc:
            raise CodexPlanError(f'Unknown {field}: {ref}.') from exc

    for item in relation_payloads:
        source_ref, target_ref = item.get('source_ref'), item.get('target_ref')
        source = resolve_relation_entity(source_ref, 'source_ref')
        target = resolve_relation_entity(target_ref, 'target_ref')
        relation_name = _text(item.get('name'), 'relation.name', required=True, maximum=100)
        relation_key = (source.pk, relation_name)
        if relation_key in relation_names or Relation.objects.filter(source=source, name=relation_name).exists():
            raise CodexPlanError(f'Duplicate relation name on {source.name}: {relation_name}.')
        if source.fields.filter(name=relation_name).exists():
            raise CodexPlanError(f'Relation name {relation_name} clashes with a field on {source.name}.')
        relation_names.add(relation_key)
        Relation.objects.create(
            source=source,
            target=target,
            kind=_choice(item, 'kind', Relation.Kind.values, Relation.Kind.FOREIGN_KEY),
            name=relation_name,
            related_name=_text(item.get('related_name'), 'relation.related_name', maximum=100),
            on_delete=_choice(item, 'on_delete', Relation.OnDelete.values, Relation.OnDelete.CASCADE),
            nullable=_bool(item, 'nullable'),
            description=_text(item.get('description'), 'relation.description', maximum=10000),
        )

    _append_design_to_project(project, user, plan, entities)


_IDENTITY_TEXT_FIELDS = {
    'description': 10000, 'brand_name': 120, 'tagline': 255, 'tone': 10000,
    'logo_rules': 10000, 'icon_library': 60, 'icon_style': 60, 'guidelines': 100000,
}


def _int_in_range(item, key, low, high, default):
    value = item.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise CodexPlanError(f'{key} must be an integer between {low} and {high}.')
    return value


def _number_in_range(item, key, low, high, default):
    value = item.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise CodexPlanError(f'identity.{key} must be a number between {low} and {high}.')
    return value


def _create_identity(user, item):
    if not isinstance(item, dict):
        raise CodexPlanError('identity must be an object.')
    name = _text(item.get('name'), 'identity.name', required=True, maximum=120)
    if VisualProfile.objects.filter(owner=user, name=name).exists():
        raise CodexPlanError(f'You already have an identity named {name}; use identity_id to reuse it.')
    values = {key: _text(item.get(key), f'identity.{key}', maximum=limit) for key, limit in _IDENTITY_TEXT_FIELDS.items()}
    values['theme_modes'] = _choice(item, 'theme_modes', VisualProfile.ThemeModes.values, VisualProfile.ThemeModes.BOTH)
    values['default_mode'] = _choice(item, 'default_mode', VisualProfile.DefaultMode.values, VisualProfile.DefaultMode.SYSTEM)
    try:
        if 'colors' in item:
            values['colors'] = identity_rules.clean_colors(item['colors'], values['theme_modes'])
        if 'shadows_dark' in item:
            values['shadows_dark'] = identity_rules.clean_shadows(item['shadows_dark'])
        for key in ('heading_font', 'body_font', 'mono_font'):
            values[key] = identity_rules.clean_font_name(item.get(key), key)
        values['font_import_url'] = identity_rules.clean_import_url(item.get('font_import_url'))
        if 'font_weights' in item:
            values['font_weights'] = identity_rules.clean_font_weights(item['font_weights'])
        if 'radii' in item:
            values['radii'] = identity_rules.clean_radii(item['radii'])
        if 'shadows' in item:
            values['shadows'] = identity_rules.clean_shadows(item['shadows'])
        if 'assets' in item:
            values['assets'] = identity_rules.clean_assets(item['assets'])
    except ValueError as exc:
        raise CodexPlanError(str(exc)) from exc
    values['base_font_size'] = _number_in_range(item, 'base_font_size', 8, 32, 16)
    values['type_scale_ratio'] = _number_in_range(item, 'type_scale_ratio', 1, 2, 1.25)
    values['spacing_unit'] = _number_in_range(item, 'spacing_unit', 1, 16, 4)
    values['accessibility_target'] = _choice(
        item, 'accessibility_target', VisualProfile.AccessibilityTarget.values, VisualProfile.AccessibilityTarget.AA
    )
    return VisualProfile.objects.create(owner=user, name=name, **values)


def _apply_identity(project, user, plan):
    """``identity`` creates and attaches a new profile, ``identity_id`` reuses one you own."""
    changed = False
    if plan.get('identity') is not None:
        project.identity = _create_identity(user, plan['identity'])
        project.include_identity = True
        changed = True
    elif plan.get('identity_id') is not None:
        identity_id = _optional_id(plan['identity_id'], 'identity_id')
        try:
            project.identity = VisualProfile.objects.get(pk=identity_id, owner=user)
        except VisualProfile.DoesNotExist as exc:
            raise CodexPlanError('identity_id must be an identity you own.') from exc
        project.include_identity = True
        changed = True
    if 'include_identity' in plan:
        if not isinstance(plan['include_identity'], bool):
            raise CodexPlanError('include_identity must be true or false.')
        project.include_identity = plan['include_identity']
        if not project.include_identity:
            project.identity = None
        changed = True
    if changed:
        project.save(update_fields=['include_identity', 'identity', 'updated_at'])


def _serialize_identity(profile):
    data = {
        key: getattr(profile, key)
        for key in (
            'id', 'name', 'description', 'brand_name', 'tagline', 'tone', 'theme_modes', 'default_mode', 'colors',
            'heading_font', 'body_font', 'mono_font', 'font_import_url', 'font_weights', 'base_font_size',
            'spacing_unit', 'radii', 'shadows', 'shadows_dark', 'assets', 'logo_rules', 'icon_library', 'icon_style', 'accessibility_target', 'guidelines',
        )
    }
    data['type_scale_ratio'] = float(profile.type_scale_ratio)
    return data


def list_identities_for_user(user):
    """Identities the token's user owns; use one of these ids as ``identity_id`` in a plan."""
    return [_serialize_identity(profile) for profile in VisualProfile.objects.filter(owner=user)]


def _append_design_to_project(project, user, plan, entities):
    """Import stack profile, resources, roles, screens, integrations and seeds.

    ``entity_ref``/``entity_refs`` may name an entity from this payload or an
    existing entity of the project by name.
    """
    _apply_identity(project, user, plan)
    lookup = {entity.name: entity for entity in project.entities.all()}
    lookup.update(entities)

    def entity_for(ref, field):
        if ref not in lookup:
            raise CodexPlanError(f'Unknown {field}: {ref}.')
        return lookup[ref]

    stack = plan.get('stack_profile')
    if stack is not None:
        if not isinstance(stack, dict):
            raise CodexPlanError('stack_profile must be an object.')
        if StackProfile.objects.filter(project=project).exists():
            raise CodexPlanError('This project already has a stack_profile.')
        StackProfile.objects.create(
            project=project,
            targets=_string_list(stack, 'targets', ['django', 'typescript', 'csharp']),
            api_naming=_choice(stack, 'api_naming', StackProfile.ApiNaming.values, StackProfile.ApiNaming.SNAKE_CASE),
            auth_method=_choice(stack, 'auth_method', StackProfile.AuthMethod.values, StackProfile.AuthMethod.SESSION),
            database=_choice(stack, 'database', StackProfile.Database.values, StackProfile.Database.POSTGRESQL),
            app_label=_text(stack.get('app_label'), 'stack_profile.app_label', maximum=100),
            namespace=_text(stack.get('namespace'), 'stack_profile.namespace', maximum=200),
        )

    resources = {}
    for item in _items(plan, 'resources'):
        entity = entity_for(item.get('entity_ref'), 'entity_ref')
        if Resource.objects.filter(entity=entity).exists():
            raise CodexPlanError(f'Entity {entity.name} already has a resource.')
        resources[entity.name] = Resource.objects.create(
            entity=entity,
            path=_text(item.get('path'), 'resource.path', required=True, maximum=100),
            title=_text(item.get('title'), 'resource.title', maximum=100),
            description=_text(item.get('description'), 'resource.description', maximum=10000),
        )

    for item in _items(plan, 'api_projections'):
        schema = item.get('schema', {})
        if not isinstance(schema, dict):
            raise CodexPlanError('api_projection.schema must be an object.')
        ApiProjection.objects.create(
            project=project,
            name=_ref(item, 'name'),
            schema=schema,
            description=_text(item.get('description'), 'api_projection.description', maximum=10000),
        )

    projections = {item.name: item for item in ApiProjection.objects.filter(project=project)}
    for item in _items(plan, 'api_operations'):
        entity = entity_for(item.get('resource_ref'), 'resource_ref')
        resource = resources.get(entity.name) or Resource.objects.filter(entity=entity).first()
        if resource is None:
            raise CodexPlanError(f'Entity {entity.name} has no resource for an API operation.')
        operation = ApiOperation.objects.create(
            resource=resource, key=_choice(item, 'key', ApiOperation.Key.values, ApiOperation.Key.CUSTOM),
            method=_text(item.get('method'), 'api_operation.method', required=True, maximum=10).upper(),
            path=_text(item.get('path'), 'api_operation.path', required=True, maximum=255),
            title=_text(item.get('title'), 'api_operation.title', required=True, maximum=100),
            description=_text(item.get('description'), 'api_operation.description', maximum=10000),
            parameters=item.get('parameters', []), request_schema=item.get('request_schema'), pagination=item.get('pagination'),
        )
        for response in _items(item, 'responses'):
            projection = projections.get(response.get('projection_ref')) if response.get('projection_ref') else None
            ApiOperationResponse.objects.create(operation=operation, status_code=response.get('status_code'),
                                                description=_text(response.get('description'), 'response.description', maximum=10000), projection=projection)

    provider_names = set(project.providers.values_list('name', flat=True))
    for item in _items(plan, 'providers'):
        name = _text(item.get('name'), 'provider.name', required=True, maximum=100)
        if name in provider_names:
            raise CodexPlanError(f'Provider name already exists in this project: {name}.')
        resource_refs = _string_list(item, 'resource_refs')
        if not resource_refs:
            raise CodexPlanError('A provider must select at least one resource_ref.')
        provider = Provider.objects.create(
            project=project,
            name=name,
            description=_text(item.get('description'), 'provider.description', maximum=10000),
        )
        selected_resources = []
        for ref in resource_refs:
            entity = entity_for(ref, 'resource_refs')
            resource = resources.get(entity.name) or Resource.objects.filter(entity=entity).first()
            if resource is None:
                raise CodexPlanError(f'Entity {entity.name} has no resource for provider {name}.')
            selected_resources.append(resource)
        provider.resources.set(selected_resources)
        provider_names.add(name)

    role_names = set(project.roles.values_list('name', flat=True))
    for item in _items(plan, 'roles'):
        role_name = _text(item.get('name'), 'role.name', required=True, maximum=100)
        if role_name in role_names:
            raise CodexPlanError(f'Role name already exists in this project: {role_name}.')
        role_names.add(role_name)
        role = Role.objects.create(
            project=project,
            name=role_name,
            description=_text(item.get('description'), 'role.description', maximum=10000),
        )
        granted = set()
        for permission in _items(item, 'permissions'):
            entity = entity_for(permission.get('resource_ref'), 'resource_ref')
            resource = resources.get(entity.name) or Resource.objects.filter(entity=entity).first()
            if resource is None:
                raise CodexPlanError(f'Entity {entity.name} has no resource to grant permissions on.')
            operation = ApiOperation.objects.filter(resource=resource, key=permission.get('operation')).first()
            if operation is None:
                raise CodexPlanError(f'Role {role_name} references an unknown API operation on {entity.name}.')
            if operation.pk in granted:
                raise CodexPlanError(f'Role {role_name} grants {operation.key} on {entity.name} more than once.')
            granted.add(operation.pk)
            RolePermission.objects.create(
                role=role,
                api_operation=operation,
                scope=_choice(permission, 'scope', RolePermission.Scope.values, RolePermission.Scope.ALL),
            )

    routes = set(project.screens.values_list('route', flat=True))
    screens = {}
    for item in _items(plan, 'screens'):
        ref = _ref(item, 'ref')
        if ref in screens:
            raise CodexPlanError(f'Duplicate screen ref: {ref}.')
        route = _text(item.get('route'), 'screen.route', required=True)
        if route in routes:
            raise CodexPlanError(f'Screen route already exists in this project: {route}.')
        routes.add(route)
        screens[ref] = Screen.objects.create(
            project=project,
            name=_text(item.get('name'), 'screen.name', required=True, maximum=100),
            route=route,
            description=_text(item.get('description'), 'screen.description', maximum=10000),
        )
        screens[ref].entities.set([entity_for(name, 'entity_refs') for name in _string_list(item, 'entity_refs')])
    for item in _items(plan, 'screens'):
        parent_ref = item.get('parent_ref')
        if parent_ref is not None:
            if parent_ref not in screens:
                raise CodexPlanError(f'Unknown parent_ref: {parent_ref}.')
            if parent_ref == item['ref']:
                raise CodexPlanError('A screen cannot be its own parent.')
            screens[item['ref']].parent = screens[parent_ref]
            screens[item['ref']].save(update_fields=['parent'])

    integration_names = set(project.integrations.values_list('name', flat=True))
    for item in _items(plan, 'integrations'):
        integration_name = _text(item.get('name'), 'integration.name', required=True, maximum=100)
        if integration_name in integration_names:
            raise CodexPlanError(f'Integration name already exists in this project: {integration_name}.')
        integration_names.add(integration_name)
        try:
            base_url = integration_rules.clean_base_url(item.get('base_url'))
            auth = integration_rules.clean_auth(item)
        except ValueError as exc:
            raise CodexPlanError(f'{integration_name}: {exc}') from exc
        rate = item.get('rate_limit_per_minute')
        integration = Integration.objects.create(
            project=project,
            name=integration_name,
            kind=_choice(item, 'kind', Integration.Kind.values, Integration.Kind.API),
            description=_text(item.get('description'), 'integration.description', maximum=10000),
            env_vars=_string_list(item, 'env_vars'),
            base_url=base_url,
            timeout_seconds=_int_in_range(item, 'timeout_seconds', 1, 120, 30),
            retries=_int_in_range(item, 'retries', 0, 5, 2),
            rate_limit_per_minute=None if rate is None else _int_in_range(item, 'rate_limit_per_minute', 1, 100000, 1),
            cache_ttl_seconds=_int_in_range(item, 'cache_ttl_seconds', 0, 31536000, 3600),
            **auth,
        )
        operation_names = set()
        for operation in _items(item, 'operations'):
            entity = None
            if operation.get('entity_ref') is not None:
                entity = entity_for(operation['entity_ref'], 'entity_ref')
            try:
                cleaned = integration_rules.clean_operation(
                    operation, entity_mapping_info(entity) if entity is not None else None
                )
            except ValueError as exc:
                raise CodexPlanError(f'{integration_name}.{operation.get("name")}: {exc}') from exc
            if cleaned['name'] in operation_names:
                raise CodexPlanError(f'Duplicate operation name on {integration_name}: {cleaned["name"]}.')
            operation_names.add(cleaned['name'])
            IntegrationOperation.objects.create(
                integration=integration,
                entity=entity,
                description=_text(operation.get('description'), 'operation.description', maximum=10000),
                **cleaned,
            )

    for item in _items(plan, 'seeds'):
        entity = entity_for(item.get('entity_ref'), 'entity_ref')
        next_order = entity.seed_rows.count()
        for offset, row in enumerate(_items(item, 'rows')):
            unknown = unknown_seed_keys(entity, row)
            if unknown:
                raise CodexPlanError(f'Seed row for {entity.name} has unknown keys: {", ".join(unknown)}.')
            SeedRow.objects.create(entity=entity, data=row, order=next_order + offset)


def scaffold_private_project(user, project_id, target, files=None):
    """Return generated ``[{path, content}]`` files for one target of a private project.

    ``files``, when given, narrows the result to just those paths — use it to fetch one file
    instead of the whole target bundle.
    """
    try:
        project = _private_projects_for(user).get(pk=project_id)
    except Project.DoesNotExist as exc:
        raise CodexPlanError('Project not found or is not private to this Codex user.') from exc
    try:
        generated = generate_files(build_spec(project), target)
    except ScaffoldError as exc:
        raise CodexPlanError(str(exc)) from exc
    if files:
        wanted = set(files)
        generated = [item for item in generated if item['path'] in wanted]
    return {'target': target, 'files': generated}


def import_project_plan_for_user(user, plan, *, return_project=False):
    if not isinstance(plan, dict):
        raise CodexPlanError('plan must be an object.')
    updated_count = 0
    with transaction.atomic():
        project = Project.objects.create(
            name=_text(plan.get('name'), 'name', required=True),
            description=_text(plan.get('description'), 'description', maximum=10000),
        )
        project.members.add(user)
        _append_plan_to_project(project, user, plan)
    return project if return_project else serialize_project(project)


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


def append_plan_to_private_project(user, project_id, plan, *, return_project=False):
    """Add a complete plan fragment to an existing private Codex project."""
    try:
        project = _private_projects_for(user).get(pk=project_id)
    except Project.DoesNotExist as exc:
        raise CodexPlanError('Project not found or is not private to this Codex user.') from exc
    with transaction.atomic():
        _append_plan_to_project(project, user, plan)
    return project if return_project else serialize_project(project)


def update_entity_in_private_project(user, project_id, entity_id, payload):
    """Partially update one entity in a private Codex project."""
    if not isinstance(payload, dict):
        raise CodexPlanError('entity must be an object.')
    try:
        project = _private_projects_for(user).get(pk=project_id)
    except Project.DoesNotExist as exc:
        raise CodexPlanError('Project not found or is not private to this Codex user.') from exc
    try:
        entity = project.entities.get(pk=entity_id)
    except Entity.DoesNotExist as exc:
        raise CodexPlanError('Entity not found in this project.') from exc

    update_fields = []
    if 'name' in payload:
        name = _text(payload.get('name'), 'entity.name', required=True, maximum=100)
        if project.entities.exclude(pk=entity.pk).filter(name=name).exists():
            raise CodexPlanError(f'Entity name already exists in this project: {name}.')
        entity.name = name
        update_fields.append('name')
    if 'description' in payload:
        entity.description = _text(payload.get('description'), 'entity.description', maximum=10000)
        update_fields.append('description')
    if not update_fields:
        raise CodexPlanError('Provide at least one of: name, description.')
    entity.save(update_fields=update_fields)
    return {
        'id': entity.id,
        'name': entity.name,
        'description': entity.description,
    }


def upsert_entity_field_in_private_project(user, project_id, entity_id, payload):
    """Create or update one named field on an entity in a private Codex project."""
    if not isinstance(payload, dict):
        raise CodexPlanError('field must be an object.')
    try:
        project = _private_projects_for(user).get(pk=project_id)
    except Project.DoesNotExist as exc:
        raise CodexPlanError('Project not found or is not private to this Codex user.') from exc
    try:
        entity = project.entities.get(pk=entity_id)
    except Entity.DoesNotExist as exc:
        raise CodexPlanError('Entity not found in this project.') from exc

    name = _text(payload.get('name'), 'field.name', required=True, maximum=100)
    field, created = Field.objects.get_or_create(entity=entity, name=name)
    field.type = _choice(payload, 'type', Field.Type.values, field.type)
    field.description = _text(payload.get('description'), 'field.description', maximum=10000)
    field.nullable = _bool(payload, 'nullable', field.nullable)
    field.unique = _bool(payload, 'unique', field.unique)
    field.default = _scalar_text(payload.get('default'), 'field.default')
    field.max_length = _max_length(payload.get('max_length'), 'field.max_length')
    if created:
        field.order = entity.fields.count() - 1
    field.save()
    return {
        'id': field.id,
        'entity_id': entity.id,
        'name': field.name,
        'type': field.type,
        'description': field.description,
        'nullable': field.nullable,
        'unique': field.unique,
        'default': field.default,
        'max_length': field.max_length,
    }


def delete_entity_field_in_private_project(user, project_id, entity_id, field_id):
    """Delete one field from an entity in a private Codex project."""
    try:
        project = _private_projects_for(user).get(pk=project_id)
        entity = project.entities.get(pk=entity_id)
        field = entity.fields.get(pk=field_id)
    except (Project.DoesNotExist, Entity.DoesNotExist, Field.DoesNotExist) as exc:
        raise CodexPlanError('Field not found in this private project entity.') from exc
    field.delete()
    return {'id': field_id, 'entity_id': entity_id, 'deleted': True}


def update_resource_in_private_project(user, project_id, entity_id, payload):
    """Partially update the API resource belonging to one private project entity."""
    if not isinstance(payload, dict):
        raise CodexPlanError('resource must be an object.')
    try:
        project = _private_projects_for(user).get(pk=project_id)
    except Project.DoesNotExist as exc:
        raise CodexPlanError('Project not found or is not private to this Codex user.') from exc
    try:
        entity = project.entities.get(pk=entity_id)
    except Entity.DoesNotExist as exc:
        raise CodexPlanError('Entity not found in this project.') from exc
    try:
        resource = Resource.objects.get(entity=entity)
    except Resource.DoesNotExist:
        if 'path' not in payload:
            raise CodexPlanError('A new resource requires path.')
        resource = Resource(entity=entity)

    update_fields = []
    if 'path' in payload:
        resource.path = _text(payload.get('path'), 'resource.path', required=True, maximum=100)
        update_fields.append('path')
    if 'title' in payload:
        resource.title = _text(payload.get('title'), 'resource.title', maximum=100)
        update_fields.append('title')
    if 'description' in payload:
        resource.description = _text(payload.get('description'), 'resource.description', maximum=10000)
        update_fields.append('description')
    if not update_fields:
        raise CodexPlanError('Provide at least one of: path, title, description.')
    if resource.pk is None:
        resource.save()
    else:
        resource.save(update_fields=update_fields)
    return {
        'id': resource.id,
        'entity_id': entity.id,
        'path': resource.path,
        'title': resource.title,
        'description': resource.description,
    }


def _serialize_api_projection(projection):
    return {
        'id': projection.id,
        'project_id': projection.project_id,
        'name': projection.name,
        'schema': projection.schema,
        'description': projection.description,
    }


def create_api_projection_in_private_project(user, project_id, payload):
    """Create one typed API projection for a private Codex project."""
    if not isinstance(payload, dict):
        raise CodexPlanError('api_projection must be an object.')
    try:
        project = _private_projects_for(user).get(pk=project_id)
    except Project.DoesNotExist as exc:
        raise CodexPlanError('Project not found or is not private to this Codex user.') from exc
    schema = payload.get('schema', {})
    if not isinstance(schema, dict):
        raise CodexPlanError('schema must be an object.')
    projection = ApiProjection.objects.create(
        project=project,
        name=_text(payload.get('name'), 'name', required=True, maximum=100),
        schema=schema,
        description=_text(payload.get('description'), 'description', maximum=10000),
    )
    return _serialize_api_projection(projection)


def update_api_projection_in_private_project(user, project_id, projection_id, payload):
    """Partially update one typed API projection in a private Codex project."""
    if not isinstance(payload, dict):
        raise CodexPlanError('api_projection must be an object.')
    try:
        project = _private_projects_for(user).get(pk=project_id)
        projection = ApiProjection.objects.get(pk=projection_id, project=project)
    except (Project.DoesNotExist, ApiProjection.DoesNotExist) as exc:
        raise CodexPlanError('API projection not found in this private project.') from exc
    fields = []
    for name, maximum in [('name', 100), ('description', 10000)]:
        if name in payload:
            setattr(projection, name, _text(payload[name], name, required=name != 'description', maximum=maximum))
            fields.append(name)
    if 'schema' in payload:
        if not isinstance(payload['schema'], dict):
            raise CodexPlanError('schema must be an object.')
        projection.schema = payload['schema']
        fields.append('schema')
    if fields:
        projection.save(update_fields=fields)
    if not fields:
        raise CodexPlanError('Provide at least one API projection field to update.')
    return _serialize_api_projection(projection)


def delete_api_projection_in_private_project(user, project_id, projection_id):
    try:
        projection = ApiProjection.objects.get(
            pk=projection_id, project__in=_private_projects_for(user).filter(pk=project_id)
        )
    except ApiProjection.DoesNotExist as exc:
        raise CodexPlanError('API projection not found in this private project.') from exc
    projection.delete()
    return {'id': projection_id, 'deleted': True}


def _serialize_api_operation(operation):
    return {'id': operation.id, 'resource_id': operation.resource_id, 'key': operation.key,
            'method': operation.method, 'path': operation.path, 'title': operation.title,
            'description': operation.description, 'parameters': operation.parameters,
            'request_schema': operation.request_schema, 'pagination': operation.pagination}


def create_api_operation_in_private_project(user, project_id, payload):
    project = _private_projects_for(user).filter(pk=project_id).first()
    if not project or not isinstance(payload, dict):
        raise CodexPlanError('api_operation must be an object in a private project.')
    resource = Resource.objects.filter(pk=_optional_id(payload.get('resource_id'), 'resource_id'), entity__project=project).first()
    if resource is None:
        raise CodexPlanError('resource_id must belong to this project.')
    for name in ('parameters', 'request_schema', 'pagination'):
        if payload.get(name) is not None and not isinstance(payload[name], (list, dict)):
            raise CodexPlanError(f'{name} must be a JSON array or object.')
    operation = ApiOperation.objects.create(resource=resource,
        key=_choice(payload, 'key', ApiOperation.Key.values, None),
        method=_text(payload.get('method'), 'method', required=True, maximum=10).upper(),
        path=_text(payload.get('path'), 'path', required=True, maximum=255),
        title=_text(payload.get('title'), 'title', required=True, maximum=100),
        description=_text(payload.get('description'), 'description', maximum=10000),
        parameters=payload.get('parameters', []), request_schema=payload.get('request_schema'), pagination=payload.get('pagination'))
    return _serialize_api_operation(operation)


def update_api_operation_in_private_project(user, project_id, operation_id, payload):
    operation = ApiOperation.objects.filter(pk=operation_id, resource__entity__project__in=_private_projects_for(user).filter(pk=project_id)).first()
    if operation is None or not isinstance(payload, dict):
        raise CodexPlanError('API operation not found in this private project.')
    fields = []
    for name, maximum in [('method', 10), ('path', 255), ('title', 100), ('description', 10000)]:
        if name in payload:
            setattr(operation, name, _text(payload[name], name, required=name != 'description', maximum=maximum).upper() if name == 'method' else _text(payload[name], name, required=name != 'description', maximum=maximum))
            fields.append(name)
    if 'key' in payload:
        operation.key = _choice(payload, 'key', ApiOperation.Key.values, operation.key); fields.append('key')
    for name in ('parameters', 'request_schema', 'pagination'):
        if name in payload:
            if payload[name] is not None and not isinstance(payload[name], (list, dict)):
                raise CodexPlanError(f'{name} must be a JSON array or object.')
            setattr(operation, name, payload[name]); fields.append(name)
    if not fields:
        raise CodexPlanError('Provide at least one API operation field to update.')
    operation.save(update_fields=fields)
    return _serialize_api_operation(operation)


def delete_api_operation_in_private_project(user, project_id, operation_id):
    operation = ApiOperation.objects.filter(pk=operation_id, resource__entity__project__in=_private_projects_for(user).filter(pk=project_id)).first()
    if operation is None:
        raise CodexPlanError('API operation not found in this private project.')
    operation.delete()
    return {'id': operation_id, 'deleted': True}


def _serialize_api_operation_response(response):
    return {'id': response.id, 'operation_id': response.operation_id, 'status_code': response.status_code,
            'description': response.description, 'projection_id': response.projection_id}


def create_api_operation_response_in_private_project(user, project_id, payload):
    project = _private_projects_for(user).filter(pk=project_id).first()
    if not project or not isinstance(payload, dict):
        raise CodexPlanError('api_operation_response must be an object in a private project.')
    operation = ApiOperation.objects.filter(pk=_optional_id(payload.get('operation_id'), 'operation_id'), resource__entity__project=project).first()
    projection_id = _optional_id(payload.get('projection_id'), 'projection_id') if payload.get('projection_id') is not None else None
    projection = ApiProjection.objects.filter(pk=projection_id, project=project).first() if projection_id else None
    if operation is None or (projection_id and projection is None):
        raise CodexPlanError('Operation and projection must belong to this project.')
    response = ApiOperationResponse.objects.create(operation=operation, status_code=payload.get('status_code'), projection=projection,
        description=_text(payload.get('description'), 'description', maximum=10000))
    return _serialize_api_operation_response(response)


def update_api_operation_response_in_private_project(user, project_id, response_id, payload):
    response = ApiOperationResponse.objects.filter(pk=response_id, operation__resource__entity__project__in=_private_projects_for(user).filter(pk=project_id)).first()
    if response is None or not isinstance(payload, dict):
        raise CodexPlanError('API operation response not found in this private project.')
    fields = []
    if 'status_code' in payload:
        response.status_code = payload['status_code']; fields.append('status_code')
    if 'description' in payload:
        response.description = _text(payload['description'], 'description', maximum=10000); fields.append('description')
    if 'projection_id' in payload:
        projection_id = _optional_id(payload['projection_id'], 'projection_id') if payload['projection_id'] is not None else None
        projection = ApiProjection.objects.filter(pk=projection_id, project=response.operation.resource.entity.project).first() if projection_id else None
        if projection_id and projection is None:
            raise CodexPlanError('projection_id must belong to this project.')
        response.projection = projection; fields.append('projection')
    if not fields:
        raise CodexPlanError('Provide at least one API operation response field to update.')
    response.save(update_fields=fields)
    return _serialize_api_operation_response(response)


def delete_api_operation_response_in_private_project(user, project_id, response_id):
    response = ApiOperationResponse.objects.filter(pk=response_id, operation__resource__entity__project__in=_private_projects_for(user).filter(pk=project_id)).first()
    if response is None:
        raise CodexPlanError('API operation response not found in this private project.')
    response.delete()
    return {'id': response_id, 'deleted': True}


def _serialize_provider(provider):
    return {
        'id': provider.id,
        'name': provider.name,
        'description': provider.description,
        'resource_ids': list(provider.resources.values_list('id', flat=True)),
    }


def _provider_selection(project, payload):
    resource_ids = payload.get('resource_ids', [])
    if not isinstance(resource_ids, list) or any(not isinstance(item, int) for item in resource_ids):
        raise CodexPlanError('resource_ids must be a list of integer ids.')
    if not resource_ids:
        raise CodexPlanError('A provider must select at least one resource.')
    resources = list(Resource.objects.filter(pk__in=resource_ids, entity__project=project))
    if len(resources) != len(set(resource_ids)):
        raise CodexPlanError('Provider selections must belong to this project.')
    return resources


def create_provider_in_private_project(user, project_id, payload):
    if not isinstance(payload, dict):
        raise CodexPlanError('provider must be an object.')
    try:
        project = _private_projects_for(user).get(pk=project_id)
    except Project.DoesNotExist as exc:
        raise CodexPlanError('Project not found or is not private to this Codex user.') from exc
    resources = _provider_selection(project, payload)
    provider = Provider.objects.create(
        project=project,
        name=_text(payload.get('name'), 'name', required=True, maximum=100),
        description=_text(payload.get('description'), 'description', maximum=10000),
    )
    provider.resources.set(resources)
    return _serialize_provider(provider)


def update_provider_in_private_project(user, project_id, provider_id, payload):
    if not isinstance(payload, dict):
        raise CodexPlanError('provider must be an object.')
    try:
        project = _private_projects_for(user).get(pk=project_id)
        provider = project.providers.get(pk=provider_id)
    except (Project.DoesNotExist, Provider.DoesNotExist) as exc:
        raise CodexPlanError('Provider not found in this private project.') from exc
    fields = []
    for name, maximum in [('name', 100), ('description', 10000)]:
        if name in payload:
            setattr(provider, name, _text(payload[name], name, required=name == 'name', maximum=maximum))
            fields.append(name)
    selection_keys = {'resource_ids'} & payload.keys()
    if selection_keys:
        merged = {
            'resource_ids': payload.get('resource_ids', list(provider.resources.values_list('id', flat=True))),
        }
        resources = _provider_selection(project, merged)
        provider.resources.set(resources)
    if not fields and not selection_keys:
        raise CodexPlanError('Provide at least one provider field to update.')
    if fields:
        provider.save(update_fields=fields)
    return _serialize_provider(provider)


def delete_provider_in_private_project(user, project_id, provider_id):
    try:
        provider = Provider.objects.get(pk=provider_id, project__in=_private_projects_for(user).filter(pk=project_id))
    except Provider.DoesNotExist as exc:
        raise CodexPlanError('Provider not found in this private project.') from exc
    provider.delete()
    return {'id': provider_id, 'deleted': True}


def update_role_in_private_project(user, project_id, role_id, payload):
    """Partially update one role and, when supplied, replace its permissions."""
    if not isinstance(payload, dict):
        raise CodexPlanError('role must be an object.')
    try:
        project = _private_projects_for(user).get(pk=project_id)
        role = project.roles.get(pk=role_id)
    except (Project.DoesNotExist, Role.DoesNotExist) as exc:
        raise CodexPlanError('Role not found in this private project.') from exc

    update_fields = []
    if 'name' in payload:
        name = _text(payload.get('name'), 'role.name', required=True, maximum=100)
        if project.roles.exclude(pk=role.pk).filter(name=name).exists():
            raise CodexPlanError(f'Role name already exists in this project: {name}.')
        role.name = name
        update_fields.append('name')
    if 'description' in payload:
        role.description = _text(payload.get('description'), 'role.description', maximum=10000)
        update_fields.append('description')

    replace_permissions = 'permissions' in payload
    permissions = []
    if replace_permissions:
        permission_payloads = _items(payload, 'permissions')
        operations = {operation.id: operation for operation in ApiOperation.objects.filter(resource__entity__project=project)}
        seen = set()
        for item in permission_payloads:
            operation_id = _optional_id(item.get('operation_id'), 'permission.operation_id')
            if operation_id not in operations:
                raise CodexPlanError('Permission operation is not in this project.')
            operation = operations[operation_id]
            scope = _choice(item, 'scope', RolePermission.Scope.values, RolePermission.Scope.ALL)
            key = operation_id
            if key in seen:
                raise CodexPlanError('A role may grant each resource operation only once.')
            seen.add(key)
            permissions.append(
                RolePermission(
                    role=role,
                    api_operation=operation,
                    scope=scope,
                )
            )

    if not update_fields and not replace_permissions:
        raise CodexPlanError('Provide at least one of: name, description, permissions.')
    with transaction.atomic():
        if update_fields:
            role.save(update_fields=update_fields)
        if replace_permissions:
            role.permissions.all().delete()
            RolePermission.objects.bulk_create(permissions)
    return {
        'id': role.id,
        'name': role.name,
        'description': role.description,
        'permissions': [
            {
                'operation_id': permission.api_operation_id,
                'scope': permission.scope,
            }
            for permission in role.permissions.order_by('id')
        ],
    }


def _serialize_screen(screen):
    return {
        'id': screen.id,
        'name': screen.name,
        'route': screen.route,
        'description': screen.description,
        'entity_ids': sorted(screen.entities.values_list('id', flat=True)),
        'parent_id': screen.parent_id,
    }


def update_screen_in_private_project(user, project_id, screen_id, payload):
    """Partially update one screen; a supplied ``entity_ids`` replaces its entities."""
    if not isinstance(payload, dict):
        raise CodexPlanError('screen must be an object.')
    try:
        project = _private_projects_for(user).get(pk=project_id)
        screen = project.screens.get(pk=screen_id)
    except (Project.DoesNotExist, Screen.DoesNotExist) as exc:
        raise CodexPlanError('Screen not found in this private project.') from exc

    update_fields = []
    if 'name' in payload:
        screen.name = _text(payload.get('name'), 'screen.name', required=True, maximum=100)
        update_fields.append('name')
    if 'route' in payload:
        route = _text(payload.get('route'), 'screen.route', required=True)
        if project.screens.exclude(pk=screen.pk).filter(route=route).exists():
            raise CodexPlanError(f'Screen route already exists in this project: {route}.')
        screen.route = route
        update_fields.append('route')
    if 'description' in payload:
        screen.description = _text(payload.get('description'), 'screen.description', maximum=10000)
        update_fields.append('description')
    if 'parent_id' in payload:
        parent_id = _optional_id(payload.get('parent_id'), 'parent_id')
        parent = None
        if parent_id is not None:
            try:
                parent = project.screens.get(pk=parent_id)
            except Screen.DoesNotExist as exc:
                raise CodexPlanError('parent_id must belong to this project.') from exc
            ancestor = parent
            while ancestor is not None:
                if ancestor.pk == screen.pk:
                    raise CodexPlanError('A screen cannot be its own ancestor.')
                ancestor = ancestor.parent
        screen.parent = parent
        update_fields.append('parent')

    entities = None
    if 'entity_ids' in payload:
        raw_ids = payload['entity_ids']
        if not isinstance(raw_ids, list):
            raise CodexPlanError('entity_ids must be a list of entity ids.')
        entity_ids = {_optional_id(value, 'entity_ids') for value in raw_ids}
        entities = list(project.entities.filter(pk__in=entity_ids))
        if len(entities) != len(entity_ids):
            raise CodexPlanError('entity_ids must all belong to this project.')

    if not update_fields and entities is None:
        raise CodexPlanError('Provide at least one of: name, route, description, parent_id, entity_ids.')
    with transaction.atomic():
        if update_fields:
            screen.save(update_fields=update_fields)
        if entities is not None:
            screen.entities.set(entities)
    return _serialize_screen(screen)


def upsert_relations_to_private_project(user, project_id, payload):
    """Create or update relations on existing entities through the Codex API."""
    if not isinstance(payload, dict):
        raise CodexPlanError('payload must be an object.')
    relation_payloads = _items(payload, 'relations')
    remove_payloads = _items(payload, 'remove_relations')
    try:
        project = _private_projects_for(user).get(pk=project_id)
    except Project.DoesNotExist as exc:
        raise CodexPlanError('Project not found or is not private to this Codex user.') from exc

    with transaction.atomic():
        entities = {entity.name: entity for entity in project.entities.all()}
        updated_count = 0
        for item in remove_payloads:
            source_name = _text(item.get('source_ref'), 'remove_relations.source_ref', required=True)
            relation_name = _text(item.get('name'), 'remove_relations.name', required=True)
            source = entities.get(source_name)
            if source is None:
                raise CodexPlanError(f'Unknown source_ref: {source_name}.')
            deleted, _ = Relation.objects.filter(source=source, name=relation_name).delete()
            updated_count += deleted

        for item in relation_payloads:
            source_name = _text(item.get('source_ref'), 'relation.source_ref', required=True)
            target_name = _text(item.get('target_ref'), 'relation.target_ref', required=True)
            relation_name = _text(item.get('name'), 'relation.name', required=True)
            source = entities.get(source_name)
            target = entities.get(target_name)
            if source is None:
                raise CodexPlanError(f'Unknown source_ref: {source_name}.')
            if target is None:
                raise CodexPlanError(f'Unknown target_ref: {target_name}.')
            if source.fields.filter(name=relation_name).exists():
                raise CodexPlanError(f'Relation name {relation_name} clashes with a field on {source_name}.')
            relation, _ = Relation.objects.get_or_create(
                source=source,
                name=relation_name,
                defaults={'target': target},
            )
            relation.target = target
            relation.kind = _choice(item, 'kind', Relation.Kind.values, Relation.Kind.FOREIGN_KEY)
            relation.related_name = _text(item.get('related_name'), 'relation.related_name', maximum=100)
            relation.on_delete = _choice(item, 'on_delete', Relation.OnDelete.values, Relation.OnDelete.CASCADE)
            relation.nullable = _bool(item, 'nullable')
            relation.description = _text(item.get('description'), 'relation.description', maximum=10000)
            relation.save()
            updated_count += 1
    return {'id': project.id, 'relations_updated': updated_count}


def update_document_in_private_project(user, project_id, document_id, payload):
    """Partially update one document in place, in an existing private project.

    Only the fields present in ``payload`` are changed, so a caller updating
    just ``content`` doesn't have to resend ``title``. ``milestone_id``/
    ``task_id``, when given, must belong to the same project, or ``null`` to
    detach - same validation as ``add_task_to_private_project``.
    """
    if not isinstance(payload, dict):
        raise CodexPlanError('document must be an object.')
    try:
        project = _private_projects_for(user).get(pk=project_id)
    except Project.DoesNotExist as exc:
        raise CodexPlanError('Project not found or is not private to this Codex user.') from exc
    try:
        document = Document.objects.get(pk=document_id, project=project)
    except Document.DoesNotExist as exc:
        raise CodexPlanError('Document not found in this project.') from exc

    update_fields = []
    if 'title' in payload:
        document.title = _text(payload.get('title'), 'document.title', required=True)
        update_fields.append('title')
    if 'kind' in payload:
        document.kind = _choice(payload, 'kind', Document.Kind.values, document.kind)
        update_fields.append('kind')
    if 'content' in payload:
        document.content = _text(payload.get('content'), 'document.content', maximum=100000)
        update_fields.append('content')
    if 'milestone_id' in payload:
        milestone_id = _optional_id(payload.get('milestone_id'), 'milestone_id')
        milestone = None
        if milestone_id is not None:
            try:
                milestone = Milestone.objects.get(pk=milestone_id, project=project)
            except Milestone.DoesNotExist as exc:
                raise CodexPlanError('milestone_id must belong to this project.') from exc
        document.milestone = milestone
        update_fields.append('milestone')
    if 'task_id' in payload:
        task_id = _optional_id(payload.get('task_id'), 'task_id')
        task = None
        if task_id is not None:
            try:
                task = Task.objects.get(pk=task_id, project=project)
            except Task.DoesNotExist as exc:
                raise CodexPlanError('task_id must belong to this project.') from exc
        document.task = task
        update_fields.append('task')

    if not update_fields:
        raise CodexPlanError(
            'At least one of title, kind, content, milestone_id, task_id must be given.'
        )

    update_fields.append('updated_at')
    document.save(update_fields=update_fields)
    return {
        'id': document.id,
        'title': document.title,
        'kind': document.kind,
        'content': document.content,
        'milestone_id': document.milestone_id,
        'task_id': document.task_id,
        'created_at': document.created_at.isoformat(),
        'updated_at': document.updated_at.isoformat(),
    }


def add_task_to_private_project(user, project_id, task_data, *, return_task=False):
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
    if return_task:
        return task
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


def _set_status(user, project_id, model, item_id, payload, label):
    if not isinstance(payload, dict) or 'status' not in payload:
        raise CodexPlanError('status is required.')
    try:
        project = _private_projects_for(user).get(pk=project_id)
    except Project.DoesNotExist as exc:
        raise CodexPlanError('Project not found or is not private to this Codex user.') from exc
    try:
        item = model.objects.get(pk=item_id, project=project)
    except model.DoesNotExist as exc:
        raise CodexPlanError(f'{label} not found in this project.') from exc
    item.status = _choice(payload, 'status', model.Status.values, item.status)
    item.save(update_fields=['status', 'updated_at'])
    return {'id': item.id, 'project_id': project.id, 'title': item.title, 'status': item.status}


def update_task_status_in_private_project(user, project_id, task_id, payload):
    """Set the status of one task; saving goes through the model so recurrence signals still fire."""
    return _set_status(user, project_id, Task, task_id, payload, 'Task')


def update_milestone_status_in_private_project(user, project_id, milestone_id, payload):
    """Set the status of one milestone in an existing private project."""
    return _set_status(user, project_id, Milestone, milestone_id, payload, 'Milestone')
