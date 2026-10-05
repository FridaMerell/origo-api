from rest_framework import serializers

from opus.access import can_access_work
from opus.models import Annotation, TextUnit

from .documents import _excerpt


class AnnotationSerializer(serializers.ModelSerializer):
    # Read-only context, so a list of annotations can be shown without fetching each unit.
    work = serializers.SerializerMethodField()
    edition_title = serializers.CharField(source="unit.version.title", read_only=True)
    chapter = serializers.SerializerMethodField()
    target_text = serializers.SerializerMethodField()
    excerpt = serializers.SerializerMethodField()
    entry = serializers.SerializerMethodField()

    class Meta:
        model = Annotation
        fields = [
            "id", "user", "unit", "lexical_entry", "target_kind", "start_offset", "end_offset", "kind", "body",
            "created_at", "updated_at", "work", "edition_title", "chapter", "target_text", "excerpt", "entry",
        ]
        read_only_fields = ["id", "user", "created_at", "updated_at"]

    def get_work(self, obj):
        return {"id": obj.unit.version.work_id, "title": obj.unit.version.work.title}

    def get_chapter(self, obj):
        parent = obj.unit.parent
        if parent is None or parent.kind != TextUnit.Kind.CHAPTER:
            return None
        return {"id": parent.id, "label": parent.label}

    def get_target_text(self, obj):
        """The annotated word or phrase; empty for a whole-unit annotation."""

        if obj.start_offset is None or obj.end_offset is None:
            return ""
        return obj.unit.content[obj.start_offset:obj.end_offset]

    def get_excerpt(self, obj):
        return _excerpt(obj.unit.content)

    def get_entry(self, obj):
        """The linked lexical entry's data, for showing a definition without another request."""

        entry = obj.lexical_entry
        if entry is None:
            return None
        return {
            "id": entry.id,
            "lemma": entry.lemma,
            "language": entry.language,
            "part_of_speech": entry.part_of_speech,
            "inflection_data": entry.inflection_data,
            "translation": entry.translation,
            "definition": entry.definition,
            "owner": entry.owner_id,
        }

    def validate_unit(self, unit):
        if not can_access_work(unit.version.work, self.context["request"].user):
            raise serializers.ValidationError("You cannot annotate a private work you do not own.")
        return unit

    def validate(self, attrs):
        instance = self.instance
        unit = attrs.get("unit") or getattr(instance, "unit", None)
        target_kind = attrs.get(
            "target_kind",
            getattr(instance, "target_kind", Annotation.TargetKind.UNIT),
        )
        start_offset = attrs.get("start_offset", getattr(instance, "start_offset", None))
        end_offset = attrs.get("end_offset", getattr(instance, "end_offset", None))

        if target_kind == Annotation.TargetKind.UNIT:
            if start_offset is not None or end_offset is not None:
                raise serializers.ValidationError(
                    {"start_offset": "Whole-unit annotations cannot have text offsets."}
                )
            return attrs

        if start_offset is None or end_offset is None:
            raise serializers.ValidationError(
                {"start_offset": "Word and phrase annotations require start_offset and end_offset."}
            )
        if start_offset >= end_offset:
            raise serializers.ValidationError(
                {"end_offset": "end_offset must be greater than start_offset."}
            )
        if unit is not None and end_offset > len(unit.content):
            raise serializers.ValidationError(
                {"end_offset": "The selection must be within the text unit's content."}
            )
        if target_kind == Annotation.TargetKind.WORD and unit is not None:
            selected_text = unit.content[start_offset:end_offset]
            if not selected_text or any(character.isspace() for character in selected_text):
                raise serializers.ValidationError(
                    {"end_offset": "A word annotation must cover one uninterrupted text token."}
                )
        return attrs
