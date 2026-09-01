from rest_framework import serializers

from tempus.models import GeoArea, Phenophase, Source


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
        if not isinstance(value, dict):
            raise serializers.ValidationError("Must be a GeoJSON geometry object.")
        if value.get("type") != "MultiPolygon":
            raise serializers.ValidationError('GeoJSON type must be "MultiPolygon".')
        if "coordinates" not in value:
            raise serializers.ValidationError("GeoJSON coordinates are required.")
        return value
