"""Shared helpers for tempus serializers."""
from rest_framework import serializers


def validate_geojson(value, expected_type):
    if not isinstance(value, dict):
        raise serializers.ValidationError("Must be a GeoJSON geometry object.")
    if value.get("type") != expected_type:
        raise serializers.ValidationError(f'GeoJSON type must be "{expected_type}".')
    if "coordinates" not in value:
        raise serializers.ValidationError("GeoJSON coordinates are required.")
    return value
