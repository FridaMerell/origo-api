"""Reusable project-label serialization."""

from rest_framework import serializers

from flux.models import Tag


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ["id", "name", "color", "created_by", "created_at"]
        read_only_fields = ["created_by", "created_at"]
