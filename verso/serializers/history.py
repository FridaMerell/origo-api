"""People, history events and interview serialization."""

from rest_framework import serializers

from verso.models import HistoryEvent, Person, PersonRelation


def _require_member(house, user):
    if house is None or not house.members.filter(pk=user.pk).exists():
        raise serializers.ValidationError("You must be a member of this house.")
    return house


def _check_same_house(attrs, instance, fields):
    """Every related object in ``fields`` (single or many) must belong to the record's house."""
    house = attrs.get("house", getattr(instance, "house", None))
    for field in fields:
        value = attrs.get(field)
        if value is None:
            continue
        for item in value if isinstance(value, (list, tuple)) else [value]:
            if item.house_id != house.pk:
                raise serializers.ValidationError({field: "Must belong to the same house."})


class PersonSerializer(serializers.ModelSerializer):
    portrait_url = serializers.SerializerMethodField()
    portrait_thumbnail_url = serializers.SerializerMethodField()

    def get_portrait_url(self, obj):
        return obj.portrait.url if obj.portrait else None

    def get_portrait_thumbnail_url(self, obj):
        return (obj.portrait.thumbnail_url or None) if obj.portrait else None

    class Meta:
        model = Person
        fields = [
            "id", "house", "name", "birth_date", "birth_date_precision", "death_date", "death_date_precision",
            "relation", "portrait", "portrait_url", "portrait_thumbnail_url", "notes", "created_at", "updated_at",
        ]
        read_only_fields = ["portrait_url", "portrait_thumbnail_url", "created_at", "updated_at"]

    def validate_house(self, house):
        return _require_member(house, self.context["request"].user)

    def validate(self, attrs):
        born = attrs.get("birth_date", getattr(self.instance, "birth_date", None))
        died = attrs.get("death_date", getattr(self.instance, "death_date", None))
        if born is not None and died is not None and died < born:
            raise serializers.ValidationError({"death_date": "Cannot be before the birth date."})
        _check_same_house(attrs, self.instance, ["portrait"])
        return attrs


class PersonRelationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PersonRelation
        fields = ["id", "house", "person", "related", "kind", "label", "start_year", "end_year", "notes", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]

    def validate_house(self, house):
        return _require_member(house, self.context["request"].user)

    def validate(self, attrs):
        person = attrs.get("person", getattr(self.instance, "person", None))
        related = attrs.get("related", getattr(self.instance, "related", None))
        kind = attrs.get("kind", getattr(self.instance, "kind", None))
        start = attrs.get("start_year", getattr(self.instance, "start_year", None))
        end = attrs.get("end_year", getattr(self.instance, "end_year", None))
        label = attrs.get("label", getattr(self.instance, "label", ""))
        if kind == PersonRelation.Kind.OTHER and not label.strip():
            raise serializers.ValidationError({"label": "A label is required when kind is 'other'."})
        if person.pk == related.pk:
            raise serializers.ValidationError({"related": "A person cannot be related to themselves."})
        _check_same_house(attrs, self.instance, ["person", "related"])
        if start is not None and end is not None and end < start:
            raise serializers.ValidationError({"end_year": "Cannot be before the start year."})
        # Symmetric kinds are stored once; reject the mirrored duplicate.
        if kind != PersonRelation.Kind.PARENT:
            mirrored = PersonRelation.objects.filter(person=related, related=person, kind=kind)
            if self.instance is not None:
                mirrored = mirrored.exclude(pk=self.instance.pk)
            if mirrored.exists():
                raise serializers.ValidationError("This relation already exists in the opposite direction.")
        return attrs


class HistoryEventSerializer(serializers.ModelSerializer):
    # ``photos`` stays a writable list of ids; this is the read-only summary for display.
    photos_detail = serializers.SerializerMethodField()

    def get_photos_detail(self, obj):
        return [{"id": p.id, "title": p.title, "thumbnail_url": p.thumbnail_url or p.url} for p in obj.photos.all()]

    class Meta:
        model = HistoryEvent
        fields = [
            "id", "house", "title", "description", "date_start", "date_end", "date_precision",
            "place", "lat", "lng", "source", "transcript", "people", "photos", "photos_detail", "author",
            "created_at", "updated_at",
        ]
        read_only_fields = ["photos_detail", "author", "created_at", "updated_at"]

    def validate_house(self, house):
        return _require_member(house, self.context["request"].user)

    def validate(self, attrs):
        start = attrs.get("date_start", getattr(self.instance, "date_start", None))
        end = attrs.get("date_end", getattr(self.instance, "date_end", None))
        if start and end and end < start:
            raise serializers.ValidationError({"date_end": "Cannot be before the start date."})
        _check_same_house(attrs, self.instance, ["people", "photos"])
        return attrs

    def create(self, validated_data):
        validated_data["author"] = self.context["request"].user
        return super().create(validated_data)
