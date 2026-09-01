import csv
import io

from django.utils import timezone
from rest_framework import serializers

from tempus.api.category_serializers import (
    SpeciesCategoryListSerializer,
    SpeciesCategoryMembershipSerializer,
    SpeciesCategorySerializer,
)
from tempus.api.reference_serializers import (
    GeoAreaSerializer,
    PhenophaseSerializer,
    SourceSerializer,
)
from tempus.models import (
    BirdnetDevice,
    BirdnetDetection,
    Checklist,
    ChecklistItem,
    GeoArea,
    Observation,
    Phenogram,
    Phenophase,
    Route,
    RouteStop,
    RouteSuggestionRun,
    Source,
    Species,
    SpeciesCategory,
    SpeciesCategoryMembership,
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


class SpeciesReferenceField(serializers.PrimaryKeyRelatedField):
    """Accept a Tempus species UUID or a Dyntaxa taxon id.

    Representation deliberately remains the internal UUID for compatibility
    with existing frontend clients.
    """

    def to_internal_value(self, data):
        if isinstance(data, int) or (isinstance(data, str) and data.isdigit()):
            try:
                return self.get_queryset().get(dyntaxa_taxon_id=int(data))
            except Species.DoesNotExist:
                self.fail("does_not_exist", pk_value=data)
        return super().to_internal_value(data)


class SpeciesSerializer(serializers.ModelSerializer):
    # Annotated per-request by SpeciesViewSet.get_queryset; False on writes.
    is_followed = serializers.BooleanField(read_only=True, default=False)

    class Meta:
        model = Species
        fields = [
            "id",
            "dyntaxa_taxon_id",
            "is_followed",
            "scientific_name",
            "swedish_name",
            "taxon_rank",
            "parent_dyntaxa_taxon_id",
            "is_active",
            "landscape_types",
            "biotopes",
            "synced_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "landscape_types",
            "biotopes",
            "created_at",
            "updated_at",
        ]


class SpeciesResolveRequestSerializer(serializers.Serializer):
    """Validate the bounded set of species ids requested by a client."""

    ids = serializers.ListField(
        child=serializers.UUIDField(),
        max_length=100,
    )

    def validate_ids(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Species ids must be unique.")
        return value


class RegisterSpeciesSerializer(serializers.Serializer):
    """Input for the "register a species from the API" action."""

    species_category = serializers.PrimaryKeyRelatedField(
        queryset=SpeciesCategory.objects.all()
    )
    dyntaxa_taxon_id = serializers.IntegerField(min_value=1)


class SpeciesChecklistImportSerializer(serializers.Serializer):
    """Input for queueing every taxon ID in an uploaded species checklist."""

    MAX_FILE_SIZE = 2 * 1024 * 1024
    MAX_TAXA = 10_000
    TAXON_ID_HEADERS = {
        "taxon id",
        "taxonid",
        "taxon id dyntaxa",
        "dyntaxa taxon id",
    }

    species_category = serializers.PrimaryKeyRelatedField(
        queryset=SpeciesCategory.objects.all()
    )
    file = serializers.FileField()

    def validate(self, attrs):
        uploaded_file = attrs["file"]
        if uploaded_file.size > self.MAX_FILE_SIZE:
            raise serializers.ValidationError(
                {
                    "file": f"The checklist must be at most {self.MAX_FILE_SIZE // (1024 * 1024)} MB."
                }
            )

        try:
            text = uploaded_file.read().decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise serializers.ValidationError(
                {"file": "The checklist must be a UTF-8 encoded CSV file."}
            ) from exc

        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=";,\t")
        except csv.Error:
            reader = csv.DictReader(io.StringIO(text), delimiter=";")
        else:
            reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        if not reader.fieldnames:
            raise serializers.ValidationError(
                {"file": "The checklist has no header row."}
            )

        normalized_headers = {
            " ".join(
                header.strip().casefold().replace("_", " ").replace("-", " ").split()
            ): header
            for header in reader.fieldnames
            if header
        }
        taxon_header = next(
            (
                original
                for normalized, original in normalized_headers.items()
                if normalized in self.TAXON_ID_HEADERS
            ),
            None,
        )
        if taxon_header is None:
            raise serializers.ValidationError(
                {"file": 'The checklist must contain a "Taxon id" column.'}
            )

        taxon_ids = []
        seen = set()
        duplicate_count = 0
        row_errors = []
        for line_number, row in enumerate(reader, start=2):
            raw_value = (row.get(taxon_header) or "").strip()
            row_values = [
                item
                for value in row.values()
                for item in (value if isinstance(value, list) else [value])
            ]
            if not raw_value and not any(
                str(value or "").strip() for value in row_values
            ):
                continue
            try:
                taxon_id = int(raw_value)
                if taxon_id < 1:
                    raise ValueError
            except (TypeError, ValueError):
                row_errors.append(
                    f"Line {line_number}: invalid Taxon id {raw_value!r}."
                )
                continue

            if taxon_id in seen:
                duplicate_count += 1
                continue
            seen.add(taxon_id)
            taxon_ids.append(taxon_id)
            if len(taxon_ids) > self.MAX_TAXA:
                raise serializers.ValidationError(
                    {
                        "file": f"The checklist may contain at most {self.MAX_TAXA} unique taxon IDs."
                    }
                )

        if row_errors:
            raise serializers.ValidationError({"file": row_errors})
        if not taxon_ids:
            raise serializers.ValidationError(
                {"file": "The checklist contains no taxon IDs."}
            )

        attrs["taxon_ids"] = taxon_ids
        attrs["duplicate_count"] = duplicate_count
        return attrs


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
        required=False,
        allow_empty=False,
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


class SeasonalOverviewQuerySerializer(serializers.Serializer):
    """Filters for the species seasonal-overview endpoint."""

    # Omitted or null means the whole country - the Phenogram rows with no
    # geo_area (see tempus.services.phenogram / docs/tempus/phenograms.md).
    geo_area = serializers.PrimaryKeyRelatedField(
        queryset=GeoArea.objects.all(), required=False, allow_null=True, default=None
    )
    min_records = serializers.IntegerField(min_value=0, required=False, default=20)
    status = serializers.CharField(
        required=False,
        default="coming_into_season,at_peak,in_season,going_out_of_season",
    )
    is_followed = serializers.BooleanField(required=False)

    def validate_status(self, value):
        statuses = [item.strip() for item in value.split(",") if item.strip()]
        if not statuses:
            raise serializers.ValidationError("Pass at least one seasonal status.")

        invalid = [item for item in statuses if not season.valid_status(item)]
        if invalid:
            raise serializers.ValidationError(
                f"Unknown status value(s): {', '.join(invalid)}."
            )
        return list(dict.fromkeys(statuses))


class SeasonalOverviewSerializer(serializers.ModelSerializer):
    """Compact species card backed by one stored area phenogram."""

    id = serializers.UUIDField(source="species.id", read_only=True)
    dyntaxa_taxon_id = serializers.IntegerField(
        source="species.dyntaxa_taxon_id", read_only=True
    )
    swedish_name = serializers.CharField(source="species.swedish_name", read_only=True)
    scientific_name = serializers.CharField(
        source="species.scientific_name", read_only=True
    )
    is_followed = serializers.BooleanField(read_only=True, default=False)
    seasonal_status = serializers.SerializerMethodField()
    activity_window = serializers.SerializerMethodField()
    habitats = serializers.SerializerMethodField()
    phenogram_scope = serializers.CharField(source="_phenogram_scope", read_only=True)
    is_low_confidence = serializers.BooleanField(
        source="_is_low_confidence", read_only=True
    )
    landscape_types = serializers.JSONField(
        source="species.landscape_types", read_only=True
    )

    class Meta:
        model = Phenogram
        fields = [
            "id",
            "dyntaxa_taxon_id",
            "swedish_name",
            "scientific_name",
            "is_followed",
            "record_count",
            "confidence",
            "years_present",
            "phenogram_scope",
            "is_low_confidence",
            "seasonal_status",
            "activity_window",
            "peak_week",
            "habitats",
            "landscape_types",
        ]
        read_only_fields = fields

    def get_seasonal_status(self, obj):
        return getattr(obj, "_seasonal_status", None) or season.status_for(obj)

    def get_activity_window(self, obj):
        return {
            "start_week": obj.window_start_week,
            "end_week": obj.window_end_week,
        }

    def get_habitats(self, obj):
        habitats = obj.species.biotopes or obj.species.landscape_types or []
        ordered = sorted(
            habitats,
            key=lambda item: item.get("significance") != "stor",
        )
        names = []
        for item in ordered:
            name = item.get("name")
            if name and name not in names:
                names.append(name)
            if len(names) == 3:
                break
        return names


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
    # Address the species by its Dyntaxa taxon id rather than the internal UUID.
    species = serializers.SlugRelatedField(
        slug_field="dyntaxa_taxon_id",
        queryset=Species.objects.all(),
    )

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


class SuggestedStopsQuerySerializer(serializers.Serializer):
    """Query params for the route ``suggested-stops`` action.

    All optional. ``taxon_id`` restricts scoring to a Dyntaxa taxon subtree
    (e.g. Aves = 4000104 for "bird stops"); ``since_days`` is the observation
    window used for scoring; ``notable_days`` is the cutoff for the "recent
    notable" list; ``max_detour_m`` drops stops that sit further than that off
    the route; ``num_stops`` caps the result; ``edge_buffer_m`` drops stops too
    close to either end of the route; ``min_gap_m`` is the minimum along-route
    spacing between stops. The last two default to fractions of route length.
    """

    taxon_id = serializers.IntegerField(min_value=1, required=False)
    since_days = serializers.IntegerField(min_value=1, max_value=365, required=False)
    notable_days = serializers.IntegerField(min_value=1, max_value=365, required=False)
    max_detour_m = serializers.FloatField(min_value=0, required=False)
    num_stops = serializers.IntegerField(min_value=1, max_value=25, required=False)
    # exclude stops within this many metres of either end of the route
    edge_buffer_m = serializers.FloatField(min_value=0, required=False)
    # minimum along-route spacing between kept stops
    min_gap_m = serializers.FloatField(min_value=0, required=False)


class RouteSuggestionRunSerializer(serializers.ModelSerializer):
    """Read-only view of a route's current rest-stop suggestion computation."""

    class Meta:
        model = RouteSuggestionRun
        fields = [
            "route",
            "status",
            "params",
            "result",
            "error",
            "created_at",
            "started_at",
            "finished_at",
        ]
        read_only_fields = fields


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


class BirdnetDeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = BirdnetDevice
        fields = [
            "id",
            "identifier",
            "name",
            "users",
            "house",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
        extra_kwargs = {"users": {"required": False}}

    def validate_house(self, house):
        request = self.context["request"]
        if house is not None and not house.members.filter(pk=request.user.pk).exists():
            raise serializers.ValidationError("You must be a member of this house.")
        return house

    def validate(self, attrs):
        house = attrs.get("house", getattr(self.instance, "house", None))
        users = attrs.get("users")
        if users is None and self.instance is not None:
            users = self.instance.users.all()
        if house is not None and users is not None:
            house_member_ids = set(house.members.values_list("pk", flat=True))
            if any(user.pk not in house_member_ids for user in users):
                raise serializers.ValidationError(
                    {"users": "All device users must be members of the selected house."}
                )
        return attrs


class BirdnetMatchedSpeciesSerializer(serializers.ModelSerializer):
    """The resolved :class:`Species` for a detection - ``null`` when the posted
    scientific name matched no registered taxon."""

    class Meta:
        model = Species
        fields = ["id", "dyntaxa_taxon_id", "scientific_name", "swedish_name"]
        read_only_fields = fields


class BirdnetDetectionSerializer(serializers.ModelSerializer):
    """Ingest/representation for a BirdNET detection.

    Wire format matches what the field device posts: ``species`` (scientific
    name) and ``detectedAt`` (ISO 8601). ``species`` (the raw name) is resolved
    to a :class:`Species` at ingest; that match is exposed read-only as
    ``matched_species`` (``null`` when nothing matched) and is not part of the
    posted payload.
    """

    species = serializers.CharField(source="scientific_name")
    matched_species = BirdnetMatchedSpeciesSerializer(
        source="species", read_only=True, allow_null=True
    )
    detectedAt = serializers.DateTimeField(source="detected_at")
    device_id = serializers.CharField(write_only=True)

    class Meta:
        model = BirdnetDetection
        fields = [
            "id",
            "species",
            "matched_species",
            "confidence",
            "detectedAt",
            "device_id",
            "created_at",
        ]
        read_only_fields = ["id", "matched_species", "created_at"]

    def create(self, validated_data):
        device_id = validated_data.pop("device_id")
        request = self.context["request"]
        try:
            validated_data["device"] = BirdnetDevice.objects.get(
                identifier=device_id,
                is_active=True,
                users=request.user,
            )
        except BirdnetDevice.DoesNotExist:
            raise serializers.ValidationError(
                {"device_id": "Unknown, inactive, or unauthorized device."}
            )
        validated_data["species"] = Species.objects.filter(
            scientific_name__iexact=validated_data["scientific_name"]
        ).first()
        return super().create(validated_data)

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation["device_id"] = instance.device.identifier
        return representation
