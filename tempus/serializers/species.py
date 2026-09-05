"""Taxonomy, seasonal-curve, and follow serializers."""
import csv
import io

from django.utils import timezone
from rest_framework import serializers

from tempus.models import (
    GeoArea,
    Phenogram,
    Species,
    SpeciesCategory,
    SpeciesCategoryMembership,
    SpeciesFollow,
)
from tempus.services import phenogram, season


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


class SpeciesCategoryMembershipSerializer(serializers.ModelSerializer):
    species = serializers.UUIDField(source="species_id", read_only=True)

    class Meta:
        model = SpeciesCategoryMembership
        fields = ["id", "species"]
        read_only_fields = ["id", "species"]


class SpeciesCategorySerializer(serializers.ModelSerializer):
    parent_category = serializers.PrimaryKeyRelatedField(read_only=True)
    is_primary = serializers.BooleanField(required=False)
    species = serializers.SerializerMethodField()
    species_memberships = SpeciesCategoryMembershipSerializer(
        source="memberships",
        many=True,
        read_only=True,
    )
    species_count = serializers.SerializerMethodField()

    class Meta:
        model = SpeciesCategory
        fields = [
            "id",
            "parent_category",
            "is_primary",
            "taxon",
            "label",
            "image_url",
            "species",
            "species_memberships",
            "species_count",
            "taxon_id",
        ]
        read_only_fields = ["id", "species", "species_memberships", "species_count"]

    def get_species_count(self, obj):
        return len(self._effective_species_ids(obj))

    def get_species(self, obj):
        return [str(pk) for pk in self._effective_species_ids(obj)]

    @staticmethod
    def _effective_species_ids(obj):
        if not hasattr(obj, "_serializer_effective_species_ids"):
            obj._serializer_effective_species_ids = obj.effective_species_ids()
        return obj._serializer_effective_species_ids

    def validate_parent_category(self, parent_category):
        if parent_category is None or self.instance is None:
            return parent_category
        ancestor = parent_category
        while ancestor is not None:
            if ancestor.pk == self.instance.pk:
                raise serializers.ValidationError(
                    "This would create a circular category chain."
                )
            ancestor = ancestor.parent_category
        return parent_category


class SpeciesCategoryListSerializerListSerializer(serializers.ListSerializer):
    """Calculate effective species once for every category in the page."""

    def to_representation(self, data):
        categories = list(data)
        if not categories:
            return []

        children_by_parent = {}
        for category_id, parent_id in SpeciesCategory.objects.values_list(
            "pk", "parent_category_id"
        ):
            children_by_parent.setdefault(parent_id, []).append(category_id)

        descendants_by_category = {}
        all_descendant_ids = set()
        for category in categories:
            descendant_ids = set()
            stack = [category.pk]
            while stack:
                category_id = stack.pop()
                if category_id in descendant_ids:
                    continue
                descendant_ids.add(category_id)
                stack.extend(children_by_parent.get(category_id, ()))
            descendants_by_category[category.pk] = descendant_ids
            all_descendant_ids.update(descendant_ids)

        species_by_category = {}
        memberships = SpeciesCategoryMembership.objects.filter(
            category_id__in=all_descendant_ids
        ).values_list("category_id", "species_id")
        for category_id, species_id in memberships:
            species_by_category.setdefault(category_id, set()).add(species_id)

        for category in categories:
            species_ids = set()
            for descendant_id in descendants_by_category[category.pk]:
                species_ids.update(species_by_category.get(descendant_id, ()))
            category._serializer_effective_species_ids = species_ids

        return super().to_representation(categories)


class SpeciesCategoryListSerializer(serializers.ModelSerializer):
    """Small category-navigation representation for paginated lists."""

    parent_category = serializers.PrimaryKeyRelatedField(read_only=True)
    species = serializers.SerializerMethodField()
    species_count = serializers.SerializerMethodField()

    def get_species(self, obj):
        return sorted(
            str(species_id)
            for species_id in getattr(obj, "_serializer_effective_species_ids", ())
        )

    def get_species_count(self, obj):
        return len(getattr(obj, "_serializer_effective_species_ids", ()))

    class Meta:
        model = SpeciesCategory
        list_serializer_class = SpeciesCategoryListSerializerListSerializer
        fields = [
            "id",
            "parent_category",
            "is_primary",
            "label",
            "image_url",
            "species",
            "species_count",
            "taxon_id",
        ]
        read_only_fields = ["id", "species", "species_count"]
