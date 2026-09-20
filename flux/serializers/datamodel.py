"""Entity, field and relation serialization."""

from rest_framework import serializers

from flux.models import Entity, Field, Relation


def _require_member(project, user):
    if not project.members.filter(pk=user.pk).exists():
        raise serializers.ValidationError("You must be a member of this project.")


class EntitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Entity
        fields = ["id", "project", "name", "description", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]

    def validate_project(self, project):
        _require_member(project, self.context["request"].user)
        return project


class FieldSerializer(serializers.ModelSerializer):
    class Meta:
        model = Field
        fields = ["id", "entity", "name", "type", "description", "nullable", "unique", "default", "max_length", "order"]

    def validate_entity(self, entity):
        _require_member(entity.project, self.context["request"].user)
        return entity

    def validate(self, attrs):
        entity = attrs.get("entity") or getattr(self.instance, "entity", None)
        name = attrs.get("name", getattr(self.instance, "name", None))
        if entity is not None and name and entity.outgoing_relations.filter(name=name).exists():
            raise serializers.ValidationError({"name": "A relation on this entity already uses this name."})
        return attrs


class RelationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Relation
        fields = ["id", "source", "target", "kind", "name", "related_name", "on_delete", "nullable", "description"]

    def validate_source(self, source):
        _require_member(source.project, self.context["request"].user)
        return source

    def validate(self, attrs):
        source = attrs.get("source") or getattr(self.instance, "source", None)
        target = attrs.get("target") or getattr(self.instance, "target", None)
        if source.project_id != target.project_id:
            raise serializers.ValidationError({"target": "Target must belong to the same project as the source."})
        name = attrs.get("name", getattr(self.instance, "name", None))
        if name and source.fields.filter(name=name).exists():
            raise serializers.ValidationError({"name": "A field on the source entity already uses this name."})
        return attrs
