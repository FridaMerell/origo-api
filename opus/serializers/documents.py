from rest_framework import serializers

from opus.access import can_access_work
from opus.models import Bookmark, Excerpt, ReadingProgress


class ReadingProgressSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReadingProgress
        fields = ["id", "user", "version", "unit", "offset", "updated_at"]
        read_only_fields = ["id", "user", "updated_at"]

    def validate_version(self, version):
        if not can_access_work(version.work, self.context["request"].user):
            raise serializers.ValidationError("You cannot use a private edition you do not own.")
        return version

    def validate(self, attrs):
        version = attrs.get("version") or getattr(self.instance, "version", None)
        unit = attrs.get("unit") or getattr(self.instance, "unit", None)
        if version is not None and unit is not None and unit.version_id != version.pk:
            raise serializers.ValidationError({"unit": "Unit must belong to the selected edition."})
        return attrs


class BookmarkSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bookmark
        fields = ["id", "user", "version", "unit", "offset", "title", "note", "created_at"]
        read_only_fields = ["id", "user", "created_at"]

    def validate_version(self, version):
        if not can_access_work(version.work, self.context["request"].user):
            raise serializers.ValidationError("You cannot use a private edition you do not own.")
        return version


class ExcerptSerializer(serializers.ModelSerializer):
    class Meta:
        model = Excerpt
        fields = [
            "id", "user", "version", "unit", "start_offset", "end_offset", "text_snapshot",
            "title", "note", "created_at",
        ]
        read_only_fields = ["id", "user", "created_at"]

    def validate_version(self, version):
        if not can_access_work(version.work, self.context["request"].user):
            raise serializers.ValidationError("You cannot use a private edition you do not own.")
        return version
