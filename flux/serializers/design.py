"""Serializers for stack, resources, roles, screens, integrations and seed data."""

from rest_framework import serializers

from flux.models import Integration, Resource, Role, RolePermission, Screen, SeedRow, StackProfile
from flux.services.scaffold.spec import unknown_seed_keys

from .datamodel import _require_member

TARGETS = {"django", "typescript", "csharp"}


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


class IntegrationSerializer(_ProjectMemberMixin, serializers.ModelSerializer):
    class Meta:
        model = Integration
        fields = ["id", "project", "name", "kind", "description", "env_vars"]

    def validate_env_vars(self, value):
        return _string_list(value, "env_vars")


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
