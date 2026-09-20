"""Read a project's design from the database into the plain spec the generators consume."""

from flux.models import Integration, Relation, Resource, Role, Screen, SeedRow, StackProfile

from .common import snake


def _integration_spec(item):
    env_vars = [name for name in (*item.env_vars, item.auth_env_var, item.auth_secret_env_var) if name]
    return {
        "name": item.name,
        "kind": item.kind,
        "description": item.description,
        "env_vars": list(dict.fromkeys(env_vars)),
        "base_url": item.base_url,
        "auth_type": item.auth_type,
        "auth_name": item.auth_name,
        "auth_env_var": item.auth_env_var,
        "auth_secret_env_var": item.auth_secret_env_var,
        "oauth_token_url": item.oauth_token_url,
        "timeout_seconds": item.timeout_seconds,
        "retries": item.retries,
        "rate_limit_per_minute": item.rate_limit_per_minute,
        "cache_ttl_seconds": item.cache_ttl_seconds,
        "operations": [
            {
                "name": op.name,
                "description": op.description,
                "method": op.method,
                "path": op.path,
                "body_format": op.body_format,
                "params": list(op.params),
                "items_path": op.items_path,
                "pagination": op.pagination,
                "pagination_config": dict(op.pagination_config),
                "filters": list(op.filters),
                "entity": op.entity.name if op.entity_id else None,
                "key_field": op.key_field,
                "mappings": list(op.mappings),
                "sync": op.sync,
                "sync_interval_minutes": op.sync_interval_minutes,
                "cache_ttl_seconds": op.cache_ttl_seconds,
                "sample_response": op.sample_response,
            }
            for op in sorted(item.operations.all(), key=lambda operation: operation.name)
        ],
    }


def entity_mapping_info(entity):
    """Field and relation info of an entity in the shape ``clean_operation`` expects."""
    return {
        "fields": {field.name: {"type": field.type, "nullable": field.nullable} for field in entity.fields.all()},
        "relations": {relation.name: relation.kind for relation in entity.outgoing_relations.all()},
    }


def unknown_seed_keys(entity, data):
    """Keys in a seed row that are neither a field, a relation nor ``id`` of the entity."""
    allowed = {"id"}
    allowed |= {snake(field.name) for field in entity.fields.all()}
    allowed |= {snake(relation.name) for relation in entity.outgoing_relations.all()}
    return sorted(key for key in data if snake(key) not in allowed)


def build_spec(project):
    try:
        stack = project.stack_profile
        stack_spec = {
            "targets": list(stack.targets),
            "api_naming": stack.api_naming,
            "auth_method": stack.auth_method,
            "database": stack.database,
            "app_label": stack.app_label,
            "namespace": stack.namespace,
        }
    except StackProfile.DoesNotExist:
        stack_spec = {
            "targets": [],
            "api_naming": StackProfile.ApiNaming.SNAKE_CASE,
            "auth_method": StackProfile.AuthMethod.SESSION,
            "database": StackProfile.Database.POSTGRESQL,
            "app_label": "",
            "namespace": "",
        }

    entities = list(project.entities.prefetch_related("fields").order_by("name"))
    relations = Relation.objects.filter(source__project=project).select_related("target").order_by("id")
    relations_by_source = {}
    for relation in relations:
        relations_by_source.setdefault(relation.source_id, []).append(
            {
                "name": relation.name,
                "target": relation.target.name,
                "kind": relation.kind,
                "related_name": relation.related_name,
                "on_delete": relation.on_delete,
                "nullable": relation.nullable,
                "description": relation.description,
            }
        )

    resources = Resource.objects.filter(entity__project=project).select_related("entity").order_by("path")
    roles = Role.objects.filter(project=project).prefetch_related("permissions__resource__entity")
    screens = Screen.objects.filter(project=project).select_related("parent").prefetch_related("entities")
    seeds = {}
    for row in SeedRow.objects.filter(entity__project=project).order_by("order", "id"):
        seeds.setdefault(row.entity_id, []).append(row.data)

    identity = None
    if project.include_identity and project.identity_id:
        profile = project.identity
        identity = {
            "name": profile.name,
            "description": profile.description,
            "brand_name": profile.brand_name,
            "tagline": profile.tagline,
            "tone": profile.tone,
            "theme_modes": profile.theme_modes,
            "default_mode": profile.default_mode,
            "colors": list(profile.colors),
            "heading_font": profile.heading_font,
            "body_font": profile.body_font,
            "mono_font": profile.mono_font,
            "font_import_url": profile.font_import_url,
            "font_weights": list(profile.font_weights),
            "base_font_size": profile.base_font_size,
            "type_scale_ratio": float(profile.type_scale_ratio),
            "spacing_unit": profile.spacing_unit,
            "radii": dict(profile.radii),
            "shadows": dict(profile.shadows),
            "shadows_dark": dict(profile.shadows_dark),
            "assets": list(profile.assets),
            "logo_rules": profile.logo_rules,
            "icon_library": profile.icon_library,
            "icon_style": profile.icon_style,
            "accessibility_target": profile.accessibility_target,
            "guidelines": profile.guidelines,
        }

    return {
        "project": {"name": project.name, "description": project.description},
        "identity": identity,
        "stack": stack_spec,
        "entities": [
            {
                "name": entity.name,
                "description": entity.description,
                "fields": [
                    {
                        "name": field.name,
                        "type": field.type,
                        "description": field.description,
                        "nullable": field.nullable,
                        "unique": field.unique,
                        "default": field.default,
                        "max_length": field.max_length,
                    }
                    for field in entity.fields.all()
                ],
                "relations": relations_by_source.get(entity.pk, []),
            }
            for entity in entities
        ],
        "resources": [
            {
                "entity": resource.entity.name,
                "path": resource.path,
                "operations": list(resource.operations),
                "filters": list(resource.filters),
                "ordering": resource.ordering,
            }
            for resource in resources
        ],
        "roles": [
            {
                "name": role.name,
                "permissions": [
                    {"resource": p.resource.entity.name, "operation": p.operation, "scope": p.scope}
                    for p in role.permissions.all()
                ],
            }
            for role in roles
        ],
        "screens": [
            {
                "name": screen.name,
                "route": screen.route,
                "description": screen.description,
                "entities": [entity.name for entity in screen.entities.all()],
                "parent": screen.parent.name if screen.parent else None,
            }
            for screen in screens
        ],
        "integrations": [
            _integration_spec(item)
            for item in Integration.objects.filter(project=project).prefetch_related("operations__entity")
        ],
        "seeds": [
            {"entity": entity.name, "rows": seeds[entity.pk]} for entity in entities if entity.pk in seeds
        ],
    }
