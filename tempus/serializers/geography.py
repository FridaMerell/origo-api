"""Geographic reference-data serializers."""
from rest_framework import serializers

from tempus.models import GeoArea


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
