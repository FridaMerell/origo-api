from rest_framework import serializers

from tempus.models import SpeciesCategory, SpeciesCategoryMembership


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
