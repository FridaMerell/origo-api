"""Small reference-data serializers used when describing species records."""
from rest_framework import serializers

from tempus.models import Phenophase, Source


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
