from rest_framework import serializers

from caelus.models import EventAlert


class EventAlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = EventAlert
        fields = ["latitude", "longitude", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]
