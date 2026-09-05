"""Checklist and observation serializers."""
from rest_framework import serializers

from tempus.models import Checklist, ChecklistItem, Observation, Species, SpeciesCategory
from tempus.services.checklists import link_observation_to_checklists, record_checklist_sighting

from .common import validate_geojson
from .species import SpeciesReferenceField


class ChecklistSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(read_only=True)
    species_count = serializers.SerializerMethodField()
    species = serializers.ListField(
        child=serializers.UUIDField(), write_only=True, required=False, default=list
    )
    species_category_taxon_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        write_only=True,
        required=False,
        default=list,
    )
    species_category_ids = serializers.ListField(
        child=serializers.UUIDField(),
        write_only=True,
        required=False,
        default=list,
    )

    class Meta:
        model = Checklist
        fields = [
            "id",
            "user",
            "name",
            "description",
            "species_count",
            "start_date",
            "end_date",
            "geo_area",
            "route",
            "species",
            "species_category_ids",
            "species_category_taxon_ids",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "user", "created_at", "updated_at"]

    def get_species_count(self, obj):
        return obj.items.values("species").distinct().count()

    def validate(self, attrs):
        attrs = super().validate(attrs)
        start = attrs.get("start_date", getattr(self.instance, "start_date", None))
        end = attrs.get("end_date", getattr(self.instance, "end_date", None))
        if start and end and end < start:
            raise serializers.ValidationError(
                {"end_date": "The end date cannot be before the start date."}
            )
        species_ids = set(attrs.get("species", []))
        category_ids = set(attrs.get("species_category_ids", []))
        category_taxon_ids = set(attrs.get("species_category_taxon_ids", []))
        if not species_ids and not category_ids and not category_taxon_ids:
            raise serializers.ValidationError(
                {"species": "Provide at least one species or species category."}
            )

        existing_species = set(
            Species.objects.filter(pk__in=species_ids).values_list("pk", flat=True)
        )
        if existing_species != species_ids:
            raise serializers.ValidationError(
                {"species": "One or more species do not exist."}
            )

        categories = list(SpeciesCategory.objects.filter(pk__in=category_ids))
        if len(categories) != len(category_ids):
            raise serializers.ValidationError(
                {"species_category_ids": "One or more categories do not exist."}
            )
        taxon_categories = list(
            SpeciesCategory.objects.filter(taxon_id__in=category_taxon_ids)
        )
        if len(taxon_categories) != len(category_taxon_ids):
            raise serializers.ValidationError(
                {"species_category_taxon_ids": "One or more categories do not exist."}
            )
        categories.extend(taxon_categories)
        attrs["_category_species_ids"] = {
            species_id
            for category in categories
            for species_id in category.effective_species_ids()
        }
        return attrs

    def create(self, validated_data):
        species_ids = set(validated_data.pop("species", []))
        category_species_ids = validated_data.pop("_category_species_ids", set())
        validated_data.pop("species_category_ids", None)
        validated_data.pop("species_category_taxon_ids", None)
        checklist = super().create(validated_data)
        all_species_ids = species_ids | category_species_ids
        ChecklistItem.objects.bulk_create(
            [
                ChecklistItem(
                    checklist=checklist,
                    species_id=species_id,
                    sequence=sequence,
                    notes="",
                )
                for sequence, species_id in enumerate(sorted(all_species_ids), start=1)
            ]
        )
        return checklist

    def validate_route(self, route):
        if route is not None and route.user_id != self.context["request"].user.pk:
            raise serializers.ValidationError("The route does not belong to you.")
        return route


class ChecklistItemSerializer(serializers.ModelSerializer):
    is_completed = serializers.SerializerMethodField()

    class Meta:
        model = ChecklistItem
        fields = [
            "id",
            "checklist",
            "species",
            "sequence",
            "notes",
            "is_completed",
        ]
        read_only_fields = ["id", "is_completed"]

    def validate_checklist(self, checklist):
        if checklist.user_id != self.context["request"].user.pk:
            raise serializers.ValidationError("The checklist does not belong to you.")
        return checklist

    def get_is_completed(self, obj):
        return obj.observations.exists()


class ChecklistRegisterItemSerializer(serializers.ModelSerializer):
    species_id = serializers.UUIDField(read_only=True)
    swedish_name = serializers.CharField(source="species.swedish_name", read_only=True)
    scientific_name = serializers.CharField(
        source="species.scientific_name", read_only=True
    )
    dyntaxa_taxon_id = serializers.IntegerField(
        source="species.dyntaxa_taxon_id", read_only=True
    )
    is_observed = serializers.BooleanField(read_only=True)
    latest_observation_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = ChecklistItem
        fields = [
            "id",
            "sequence",
            "notes",
            "species_id",
            "swedish_name",
            "scientific_name",
            "dyntaxa_taxon_id",
            "is_observed",
            "latest_observation_id",
        ]


class ObservationSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(read_only=True)
    species = SpeciesReferenceField(
        queryset=Species.objects.all(),
        style={"base_template": "input.html"},
    )
    checklist_names = serializers.SerializerMethodField()
    checklist_items = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=ChecklistItem.objects.all(),
        required=False,
    )

    class Meta:
        model = Observation
        fields = [
            "id",
            "user",
            "species",
            "checklist_items",
            "observed_at",
            "location",
            "checklist_names",
            "count",
            "notes",
            "created_at",
        ]
        read_only_fields = ["id", "user", "created_at", "checklist_names"]

    def validate(self, attrs):
        items = attrs.get("checklist_items")
        species = attrs.get("species") or getattr(self.instance, "species", None)
        if items is None and self.instance is not None and "species" in attrs:
            items = list(self.instance.checklist_items.all())
        if items is not None:
            user = self.context["request"].user
            if any(item.checklist.user_id != user.pk for item in items):
                raise serializers.ValidationError(
                    {"checklist_items": "Every checklist must belong to you."}
                )
            if species and any(item.species_id != species.pk for item in items):
                raise serializers.ValidationError(
                    {"checklist_items": "Every item must match the observed species."}
                )
        return attrs

    def get_checklist_names(self, obj):
        return [item.checklist.name for item in obj.checklist_items.all()]

    def validate_location(self, value):
        return validate_geojson(value, "Point")

    def create(self, validated_data):
        items = validated_data.pop("checklist_items", [])
        user = validated_data.pop("user")
        if items:
            validated_data.pop("species")
            return record_checklist_sighting(
                user=user,
                checklist_items=items,
                **validated_data,
            )
        observation = Observation.objects.create(user=user, **validated_data)
        link_observation_to_checklists(observation)
        return observation

    def update(self, instance, validated_data):
        items = validated_data.pop("checklist_items", None)
        instance = super().update(instance, validated_data)
        if items is not None:
            instance.checklist_items.set(items)
        link_observation_to_checklists(instance)
        return instance
