"""Serializers for stack, resources, roles, screens, integrations and seed data."""

from rest_framework import serializers

from flux.models import Integration, IntegrationOperation, Resource, Role, RolePermission, Screen, SeedRow, StackProfile
from flux.services.scaffold import integration as integration_rules
from flux.services.scaffold.spec import entity_mapping_info, unknown_seed_keys

from .datamodel import _require_member

TARGETS = {"django", "typescript", "csharp"}


def _checked(function, value):
    try:
        return function(value)
    except ValueError as exc:
        raise serializers.ValidationError(str(exc)) from exc


def _string_list(value, label):
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise serializers.ValidationError(f"{label} must be a list of strings.")
    return value


class _ProjectMemberMixin:
    def validate_project(self, project):
        _require_member(project, self.context["request"].user)
        return project


class StackProfileSerializer(_ProjectMemberMixin, serializers.ModelSerializer):
    class Meta:
        model = StackProfile
        fields = ["id", "project", "targets", "api_naming", "auth_method", "database", "app_label", "namespace"]

    def validate_targets(self, value):
        _string_list(value, "targets")
        unknown = set(value) - TARGETS
        if unknown:
            raise serializers.ValidationError(f"Unknown targets: {', '.join(sorted(unknown))}.")
        return value


class ResourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Resource
        fields = ["id", "entity", "path", "operations", "filters", "ordering"]

    def validate_entity(self, entity):
        _require_member(entity.project, self.context["request"].user)
        return entity

    def validate_operations(self, value):
        _string_list(value, "operations")
        unknown = set(value) - set(Resource.Operation.values)
        if unknown:
            raise serializers.ValidationError(f"Unknown operations: {', '.join(sorted(unknown))}.")
        return value

    def validate_filters(self, value):
        return _string_list(value, "filters")


class RoleSerializer(_ProjectMemberMixin, serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ["id", "project", "name", "description"]


class RolePermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = RolePermission
        fields = ["id", "role", "resource", "operation", "scope"]

    def validate_role(self, role):
        _require_member(role.project, self.context["request"].user)
        return role

    def validate(self, attrs):
        role = attrs.get("role") or getattr(self.instance, "role", None)
        resource = attrs.get("resource") or getattr(self.instance, "resource", None)
        if resource.entity.project_id != role.project_id:
            raise serializers.ValidationError({"resource": "Resource must belong to the same project as the role."})
        return attrs


class ScreenSerializer(_ProjectMemberMixin, serializers.ModelSerializer):
    class Meta:
        model = Screen
        fields = ["id", "project", "name", "route", "description", "entities", "parent"]

    def validate(self, attrs):
        project = attrs.get("project") or getattr(self.instance, "project", None)
        parent = attrs.get("parent", getattr(self.instance, "parent", None))
        if parent is not None and parent.project_id != project.pk:
            raise serializers.ValidationError({"parent": "Parent must belong to the same project."})
        if parent is not None and self.instance is not None and parent.pk == self.instance.pk:
            raise serializers.ValidationError({"parent": "A screen cannot be its own parent."})
        for entity in attrs.get("entities", []):
            if entity.project_id != project.pk:
                raise serializers.ValidationError({"entities": "Entities must belong to the same project."})
        return attrs


_AUTH_KEYS = ("auth_type", "auth_name", "auth_env_var", "auth_secret_env_var", "oauth_token_url")


class IntegrationSerializer(_ProjectMemberMixin, serializers.ModelSerializer):
    class Meta:
        model = Integration
        fields = [
            "id", "project", "name", "kind", "description", "env_vars", "base_url", "auth_type", "auth_name",
            "auth_env_var", "auth_secret_env_var", "oauth_token_url", "timeout_seconds", "retries",
            "rate_limit_per_minute", "cache_ttl_seconds",
        ]

    def validate_env_vars(self, value):
        return _string_list(value, "env_vars")

    def validate_base_url(self, value):
        return _checked(integration_rules.clean_base_url, value)

    def validate_timeout_seconds(self, value):
        if not 1 <= value <= 120:
            raise serializers.ValidationError("timeout_seconds must be between 1 and 120.")
        return value

    def validate_retries(self, value):
        if value > 5:
            raise serializers.ValidationError("retries must be at most 5.")
        return value

    def validate(self, attrs):
        merged = {key: attrs.get(key, getattr(self.instance, key, "")) for key in _AUTH_KEYS}
        try:
            attrs.update(integration_rules.clean_auth(merged))
        except ValueError as exc:
            raise serializers.ValidationError({"auth_type": str(exc)}) from exc
        return attrs


_OPERATION_KEYS = (
    "name", "method", "path", "body_format", "params", "items_path", "pagination", "pagination_config", "filters",
    "key_field", "mappings", "sync", "sync_interval_minutes", "cache_ttl_seconds", "sample_response",
)


class IntegrationOperationSerializer(serializers.ModelSerializer):
    class Meta:
        model = IntegrationOperation
        fields = ["id", "integration", "description", *_OPERATION_KEYS, "entity"]

    def validate_integration(self, integration):
        _require_member(integration.project, self.context["request"].user)
        return integration

    def validate(self, attrs):
        current = self.instance
        integration = attrs.get("integration") or current.integration
        entity = attrs.get("entity", current.entity if current else None)
        if entity is not None and entity.project_id != integration.project_id:
            raise serializers.ValidationError({"entity": "Entity must belong to the same project as the integration."})
        data = {key: attrs[key] if key in attrs else getattr(current, key, None) for key in _OPERATION_KEYS}
        for key in ("params", "filters", "mappings"):
            data[key] = data[key] if data[key] is not None else []
        data["pagination_config"] = data["pagination_config"] or {}
        try:
            cleaned = integration_rules.clean_operation(data, entity_mapping_info(entity) if entity else None)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        attrs.update(cleaned)
        return attrs


class SeedRowSerializer(serializers.ModelSerializer):
    class Meta:
        model = SeedRow
        fields = ["id", "entity", "data", "order"]

    def validate_entity(self, entity):
        _require_member(entity.project, self.context["request"].user)
        return entity

    def validate_data(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("data must be an object.")
        return value

    def validate(self, attrs):
        entity = attrs.get("entity") or getattr(self.instance, "entity", None)
        data = attrs.get("data", getattr(self.instance, "data", {}))
        unknown = unknown_seed_keys(entity, data)
        if unknown:
            raise serializers.ValidationError({"data": f"Unknown keys: {', '.join(unknown)}."})
        return attrs
