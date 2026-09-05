"""BirdNET device and detection serializers."""
from rest_framework import serializers

from tempus.models import BirdnetDetection, BirdnetDevice, Species


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
