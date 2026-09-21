from rest_framework import serializers

from opus.access import can_access_work
from opus.models import Edition, Shelf, SourceFile, TextUnit, Work


class WorkSerializer(serializers.ModelSerializer):
    class Meta:
        model = Work
        fields = [
            "id", "title", "author", "year", "owner", "is_private", "shelves",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "owner", "created_at", "updated_at"]

    def validate_is_private(self, value):
        if (
            self.instance is not None
            and self.instance.owner_id != self.context["request"].user.pk
            and value != self.instance.is_private
        ):
            raise serializers.ValidationError("Only the work owner can change its privacy.")
        return value


class ShelfSerializer(serializers.ModelSerializer):
    class Meta:
        model = Shelf
        fields = ["id", "name"]
        read_only_fields = ["id"]


class EditionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Edition
        fields = ["id", "work", "title", "language", "edition", "source", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_work(self, work):
        request = self.context["request"]
        if work.is_private and work.owner_id != request.user.pk:
            raise serializers.ValidationError("You cannot add an edition to a private work you do not own.")
        return work


class SourceFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = SourceFile
        fields = [
            "id", "version", "storage_key", "original_filename", "content_hash", "file_type",
            "import_status", "failure_detail", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "storage_key", "original_filename", "content_hash", "file_type", "import_status",
            "failure_detail", "created_at", "updated_at",
        ]

    def validate_version(self, version):
        if not can_access_work(version.work, self.context["request"].user):
            raise serializers.ValidationError("You cannot use a private edition you do not own.")
        return version


class TextUnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = TextUnit
        fields = ["id", "version", "parent", "kind", "position", "content", "label", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_version(self, version):
        if not can_access_work(version.work, self.context["request"].user):
            raise serializers.ValidationError("You cannot use a private edition you do not own.")
        return version

    def validate(self, attrs):
        version = attrs.get("version") or getattr(self.instance, "version", None)
        parent = attrs.get("parent", getattr(self.instance, "parent", None))
        if parent is not None and version is not None and parent.version_id != version.pk:
            raise serializers.ValidationError({"parent": "Parent must belong to the same edition."})
        if parent is not None and self.instance is not None:
            ancestor = parent
            while ancestor is not None:
                if ancestor.pk == self.instance.pk:
                    raise serializers.ValidationError({"parent": "This would create a circular text hierarchy."})
                ancestor = ancestor.parent
        return attrs
