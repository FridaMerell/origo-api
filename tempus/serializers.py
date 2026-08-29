from django.utils import timezone
from rest_framework import serializers

from tempus.models import (
    Checklist,
    ChecklistItem,
    GeoArea,
    Observation,
    Phenogram,
    Phenophase,
    Route,
    RouteStop,
    Source,
    Species,
    SpeciesCategory,
    SpeciesFollow,
)
from tempus.services import phenogram, season
from tempus.services.checklists import (
    link_observation_to_checklists,
    record_checklist_sighting,
)


def validate_geojson(value, expected_type):
    if not isinstance(value, dict):
        raise serializers.ValidationError("Must be a GeoJSON geometry object.")
    if value.get("type") != expected_type:
        raise serializers.ValidationError(f'GeoJSON type must be "{expected_type}".')
    if "coordinates" not in value:
        raise serializers.ValidationError("GeoJSON coordinates are required.")
    return value


class SpeciesSerializer(serializers.ModelSerializer):
    class Meta:
        model = Species
        fields = [
            "id",
            "dyntaxa_taxon_id",
            "scientific_name",
            "swedish_name",
            "taxon_rank",
            "parent_dyntaxa_taxon_id",
            "is_active",
            "api_data",
            "landscape_types",
            "biotopes",
            "synced_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id", "landscape_types", "biotopes", "created_at", "updated_at",
        ]


class SpeciesCategorySerializer(serializers.ModelSerializer):
    species = serializers.PrimaryKeyRelatedField(many=True, read_only=True, )
    species_count = serializers.IntegerField(source="species.count", read_only=True)

    class Meta:
        model = SpeciesCategory
        fields = ["id", "taxon", "label", "image_url", "species", "species_count", "taxon_id"]
        read_only_fields = ["id", "species"]


class RegisterSpeciesSerializer(serializers.Serializer):
    """Input for the "register a species from the API" action."""

    species_category = serializers.PrimaryKeyRelatedField(
        queryset=SpeciesCategory.objects.all()
    )
    dyntaxa_taxon_id = serializers.IntegerField(min_value=1)


class SpeciesResyncSerializer(serializers.Serializer):
    """Body for the bulk ``species/resync/`` action.

    Pick one selector: ``taxa`` (explicit dyntaxa ids), ``missing`` (species
    whose named JSON field is empty - to backfill a new Artfakta field),
    ``all`` (every species), or neither - which resyncs species not synced
    within ``older_than_days`` (default 30) plus any never synced.
    """

    taxa = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, allow_empty=False
    )
    missing = serializers.ListField(
        child=serializers.ChoiceField(choices=["biotopes", "landscape_types"]),
        required=False, allow_empty=False,
    )
    older_than_days = serializers.IntegerField(min_value=0, required=False)
    all = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        picked = [k for k in ("taxa", "missing") if attrs.get(k)]
        if attrs.get("all"):
            picked.append("all")
        if len(picked) > 1:
            raise serializers.ValidationError(
                f"Pass at most one of {', '.join(picked)}."
            )
        return attrs


class GeneratePhenogramsSerializer(serializers.Serializer):
    """Body for the bulk ``species/generate-phenograms/`` action.

    ``taxa`` limits to explicit dyntaxa ids; omit for every species. ``refresh``
    (default true) rebuilds existing curves too.
    """

    taxa = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, allow_empty=False
    )
    refresh = serializers.BooleanField(required=False, default=True)


class SpeciesSearchSerializer(serializers.Serializer):
    """Query params for the "search species in the API" action."""

    q = serializers.CharField()
    under_taxon_id = serializers.IntegerField(min_value=1, required=False)
    limit = serializers.IntegerField(min_value=1, required=False)

    def validate_q(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Pass a non-empty search string.")
        return value


class PhenogramQuerySerializer(serializers.Serializer):
    """Query params / body for the species ``phenogram`` action.

    ``geo_area`` and ``years`` identify the stored row; ``refresh`` forces a
    rebuild from the observation API instead of reading it.
    """

    geo_area = serializers.PrimaryKeyRelatedField(
        queryset=GeoArea.objects.all(), required=False
    )
    years = serializers.IntegerField(
        min_value=1, max_value=phenogram.MAX_YEARS, required=False
    )
    refresh = serializers.BooleanField(required=False)


class PhenogramSerializer(serializers.ModelSerializer):
    activity_window = serializers.SerializerMethodField()
    stale = serializers.SerializerMethodField()
    seasonal_status = serializers.SerializerMethodField()

    class Meta:
        model = Phenogram
        fields = [
            "id",
            "species",
            "geo_area",
            "years",
            "date_from",
            "date_to",
            "computed_at",
            "stale",
            "record_count",
            "record_limit_hit",
            "sample_count",
            "years_present",
            "smooth_weeks",
            "declustered",
            "peak_week",
            "activity_window",
            "start_day_of_year",
            "peak_start_day",
            "peak_end_day",
            "end_day_of_year",
            "confidence",
            "seasonal_status",
            "weeks",
        ]
        read_only_fields = fields

    def get_activity_window(self, obj):
        return {"start_week": obj.window_start_week, "end_week": obj.window_end_week}

    def get_stale(self, obj):
        return (timezone.now() - obj.computed_at).days > 90

    def get_seasonal_status(self, obj):
        """Where today sits in this curve: ``status`` plus the ``is_in_season``
        / ``is_coming_into_season`` / ``is_going_out_of_season`` / ``at_peak``
        booleans and ``days_until_start`` / ``days_until_end``."""
        return season.status_for(obj)


class SpeciesFollowSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = SpeciesFollow
        fields = [
            "id",
            "user",
            "species",
            "priority",
            "notifications_enabled",
            "notes",
            "created_at",
        ]
        read_only_fields = ["id", "user", "created_at"]


class PhenophaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Phenophase
        fields = ["id", "code", "label"]
        read_only_fields = ["id"]


class SourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Source
        fields = ["id", "title", "url", "publisher", "accessed_at"]
        read_only_fields = ["id"]


class GeoAreaSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeoArea
        fields = ["id", "name", "kind", "country_code", "geometry"]
        read_only_fields = ["id"]

    def validate_geometry(self, value):
        return validate_geojson(value, "MultiPolygon")


class RouteSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Route
        fields = [
            "id",
            "user",
            "name",
            "planned_date",
            "geometry",
            "corridor_metres",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "user", "created_at", "updated_at"]

    def validate_geometry(self, value):
        return validate_geojson(value, "LineString")


class RouteStopSerializer(serializers.ModelSerializer):
    class Meta:
        model = RouteStop
        fields = ["id", "route", "sequence", "name", "location", "planned_at"]
        read_only_fields = ["id"]

    def validate_route(self, route):
        if route.user_id != self.context["request"].user.pk:
            raise serializers.ValidationError("The route does not belong to you.")
        return route

    def validate_location(self, value):
        return validate_geojson(value, "Point")


class ChecklistSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(read_only=True)
    species_count = serializers.SerializerMethodField()

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
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "user", "created_at", "updated_at"]

    def get_species_count(self, obj):
        return obj.items.values("species").distinct().count()

    def validate_route(self, route):
        if route is not None and route.user_id != self.context["request"].user.pk:
            raise serializers.ValidationError("The route does not belong to you.")
        return route

    def validate(self, attrs):
        start = attrs.get("start_date", getattr(self.instance, "start_date", None))
        end = attrs.get("end_date", getattr(self.instance, "end_date", None))
        if start and end and end < start:
            raise serializers.ValidationError(
                {"end_date": "The end date cannot be before the start date."}
            )
        return attrs


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


class ObservationSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(read_only=True)
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
            "count",
            "notes",
            "created_at",
        ]
        read_only_fields = ["id", "user", "created_at"]

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
