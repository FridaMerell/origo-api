from rest_framework import serializers

from opus.access import can_access_work
from opus.models import Annotation


class AnnotationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Annotation
        fields = [
            "id", "user", "unit", "lexical_entry", "start_offset", "end_offset", "kind", "body",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "user", "created_at", "updated_at"]

    def validate_unit(self, unit):
        if not can_access_work(unit.version.work, self.context["request"].user):
            raise serializers.ValidationError("You cannot annotate a private work you do not own.")
        return unit
