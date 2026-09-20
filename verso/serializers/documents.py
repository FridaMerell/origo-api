"""Document serialization."""

from rest_framework import serializers

from verso.models import Document


class DocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Document
        fields = [
            "id", "house", "venture", "tags", "people", "author",
            "title", "description", "url", "file_name", "content_type", "size",
            "document_date", "date_precision", "source", "transcription",
            "created_at", "updated_at",
        ]
        read_only_fields = ["author", "created_at", "updated_at"]

    def validate_house(self, house):
        if house is None or not house.members.filter(pk=self.context["request"].user.pk).exists():
            raise serializers.ValidationError("You must be a member of this house.")
        return house

    def validate(self, attrs):
        house = attrs.get("house", getattr(self.instance, "house", None))
        venture = attrs.get("venture", getattr(self.instance, "venture", None))
        if venture is not None and venture.house_id != house.pk:
            raise serializers.ValidationError({"venture": "The venture must belong to the same house."})
        for field in ("tags", "people"):
            for item in attrs.get(field, []):
                if item.house_id != house.pk:
                    raise serializers.ValidationError({field: f"All {field} must belong to the same house."})
        return attrs

    def create(self, validated_data):
        validated_data["author"] = self.context["request"].user
        return super().create(validated_data)
