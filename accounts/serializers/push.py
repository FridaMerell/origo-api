"""Web Push subscription serializers."""

from rest_framework import serializers

from accounts.models import WebPushSubscription


class WebPushSubscriptionSerializer(serializers.ModelSerializer):
    """Read representation for the optional list endpoint."""

    class Meta:
        model = WebPushSubscription
        fields = [
            "id",
            "endpoint",
            "tenant",
            "user_agent",
            "created_at",
            "last_success_at",
            "is_active",
        ]
        read_only_fields = fields


class WebPushSubscriptionWriteSerializer(serializers.Serializer):
    """Validates the ``PushSubscription`` shape the frontend posts."""

    endpoint = serializers.URLField(max_length=512)
    keys = serializers.DictField(child=serializers.CharField(), write_only=True)
    tenant = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    user_agent = serializers.CharField(
        max_length=400, required=False, allow_blank=True, default=""
    )

    def validate_endpoint(self, value):
        if not value.startswith("https://"):
            raise serializers.ValidationError("endpoint must start with https://")
        return value

    def validate_keys(self, value):
        missing = [key for key in ("p256dh", "auth") if not value.get(key)]
        if missing:
            raise serializers.ValidationError(f"keys missing: {', '.join(missing)}")
        return value


class WebPushEndpointSerializer(serializers.Serializer):
    """Body for ``DELETE`` – just the endpoint to retire."""

    endpoint = serializers.URLField(max_length=512)
