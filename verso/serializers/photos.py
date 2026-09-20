"""Photo, album and tag serialization."""

from rest_framework import serializers

from verso.models import Album, Photo, Tag


def _require_member(house, user):
    if house is None or not house.members.filter(pk=user.pk).exists():
        raise serializers.ValidationError("You must be a member of this house.")
    return house


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ["id", "house", "name"]

    def validate_house(self, house):
        return _require_member(house, self.context["request"].user)


class AlbumSerializer(serializers.ModelSerializer):
    photo_count = serializers.IntegerField(source="photos.count", read_only=True)

    class Meta:
        model = Album
        fields = ["id", "house", "venture", "name", "description", "kind", "cover", "photo_count", "created_at", "updated_at"]
        read_only_fields = ["photo_count", "created_at", "updated_at"]

    def validate_house(self, house):
        return _require_member(house, self.context["request"].user)

    def validate(self, attrs):
        house = attrs.get("house", getattr(self.instance, "house", None))
        venture = attrs.get("venture", getattr(self.instance, "venture", None))
        cover = attrs.get("cover", getattr(self.instance, "cover", None))
        if venture is not None and venture.house_id != house.pk:
            raise serializers.ValidationError({"venture": "The venture must belong to the same house."})
        if cover is not None and cover.house_id != house.pk:
            raise serializers.ValidationError({"cover": "The cover photo must belong to the same house."})
        return attrs


class PhotoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Photo
        fields = [
            "id", "house", "venture", "task", "albums", "tags", "author",
            "url", "thumbnail_url", "width", "height",
            "title", "description", "taken_at", "date_precision", "lat", "lng",
            "place", "source", "transcription", "credit", "people",
            "stage", "pair", "created_at", "updated_at",
        ]
        read_only_fields = ["author", "created_at", "updated_at"]

    def validate_house(self, house):
        return _require_member(house, self.context["request"].user)

    def validate(self, attrs):
        house = attrs.get("house", getattr(self.instance, "house", None))
        venture = attrs.get("venture", getattr(self.instance, "venture", None))
        task = attrs.get("task", getattr(self.instance, "task", None))
        pair = attrs.get("pair", getattr(self.instance, "pair", None))

        if venture is not None and venture.house_id != house.pk:
            raise serializers.ValidationError({"venture": "The venture must belong to the same house."})
        if task is not None:
            if venture is None or task.venture_id != venture.pk:
                raise serializers.ValidationError({"task": "The task must belong to the photo's venture."})
        if pair is not None:
            if pair.house_id != house.pk:
                raise serializers.ValidationError({"pair": "The paired photo must belong to the same house."})
            if self.instance is not None and pair.pk == self.instance.pk:
                raise serializers.ValidationError({"pair": "A photo cannot be paired with itself."})
        for field in ("albums", "tags", "people"):
            for item in attrs.get(field, []):
                if item.house_id != house.pk:
                    raise serializers.ValidationError({field: f"All {field} must belong to the same house."})
        return attrs

    def create(self, validated_data):
        validated_data["author"] = self.context["request"].user
        return super().create(validated_data)
