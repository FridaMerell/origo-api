"""User representation serializers."""

from django.contrib.auth import get_user_model
from rest_framework import serializers

from accounts.models import Notification

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    open_notifications = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name", "open_notifications"]

    def get_open_notifications(self, obj):
        count = getattr(obj, "open_notifications", None)
        if count is not None:
            return count
        return Notification.objects.filter(user=obj, is_read=False).count()
