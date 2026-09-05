"""Notification representation serializers."""

from rest_framework import serializers

from accounts.models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "domain", "message", "is_read", "created_at", "sent_by"]
        read_only_fields = ["domain", "message", "created_at", "sent_by"]
