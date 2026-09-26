from rest_framework import serializers

from opus.access import can_access_work
from opus.models import Annotation


class AnnotationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Annotation
        fields = [
            "id", "user", "unit", "lexical_entry", "target_kind", "start_offset", "end_offset", "kind", "body",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "user", "created_at", "updated_at"]

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
