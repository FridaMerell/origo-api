"""Shared-house serialization."""

from rest_framework import serializers

from verso.models import House


class HouseSerializer(serializers.ModelSerializer):
    class Meta:
        model = House
        fields = ["id", "name", "address", "members", "created_at", "updated_at", "lat", "lng"]
        read_only_fields = ["created_at", "updated_at"]
