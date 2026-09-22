from rest_framework import serializers

from opus.access import can_access_work
from opus.models import Author, Edition, Shelf, SourceFile, TextUnit, Work, WorkContributor
from opus.serializers.people import WorkContributorSerializer


class WorkSerializer(serializers.ModelSerializer):
    contributors = WorkContributorSerializer(many=True, read_only=True)
    editions = serializers.SerializerMethodField()
    shelf_names = serializers.SerializerMethodField()

    class Meta:
        model = Work
        fields = [
            "id", "title", "year", "owner", "is_private", "shelves",
            "contributors", "editions", "shelf_names", "created_at", "updated_at",
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

    def get_editions(self, obj):
        return EditionSerializer(
            obj.editions.all(), many=True, context=self.context
        ).data

    def get_shelf_names(self, obj):
        return [shelf.name for shelf in obj.shelves.all()]


class CreateWorkEditionSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    language = serializers.CharField(max_length=16)
    edition = serializers.CharField(max_length=255, required=False, allow_blank=True)
    source = serializers.CharField(max_length=500, required=False, allow_blank=True)


class CreateWorkWithEditionsSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    year = serializers.CharField(max_length=100, required=False, allow_blank=True)
    is_private = serializers.BooleanField(required=False, default=False)
    shelves = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Shelf.objects.all(), required=False
    )
    author = serializers.CharField(max_length=255, required=False, allow_blank=True)
    editions = CreateWorkEditionSerializer(many=True)

    def validate_editions(self, editions):
        if not editions:
            raise serializers.ValidationError("At least one edition is required.")
        return editions

    def create(self, validated_data):
        editions = validated_data.pop("editions")
        author_name = validated_data.pop("author", "").strip()
        shelves = validated_data.pop("shelves", [])
        owner = self.context["request"].user

        from django.db import transaction

        with transaction.atomic():
            work = Work.objects.create(owner=owner, **validated_data)
            work.shelves.set(shelves)

            if author_name:
                author = Author.objects.filter(name__iexact=author_name).first()
                if author is None:
                    author = Author.objects.create(name=author_name)
                WorkContributor.objects.create(
                    work=work,
                    author=author,
                    role=WorkContributor.Role.AUTHOR,
                    display_order=0,
                )

            Edition.objects.bulk_create(
                [Edition(work=work, **edition) for edition in editions]
            )
        return work

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
