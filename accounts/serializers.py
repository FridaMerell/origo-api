from django.contrib.auth import authenticate, get_user_model
from rest_framework import serializers

from accounts.models import Notification

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name']


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ['id', 'domain', 'message', 'is_read', 'created_at', 'sent_by']
        read_only_fields = ['domain', 'message', 'created_at', 'sent_by']


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = authenticate(
            request=self.context.get('request'),
            username=attrs['username'],
            password=attrs['password'],
        )
        if user is None:
            raise serializers.ValidationError('Invalid credentials.')
        attrs['user'] = user
        return attrs
