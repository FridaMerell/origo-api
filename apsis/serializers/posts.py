"""Post serialization."""

from rest_framework import serializers

from apsis.models import Post


class PostSerializer(serializers.ModelSerializer):
    author = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Post
        fields = [
            "id",
            "files",
            "author",
            "geolocation",
            "content",
            "name",
            "created_at",
        ]
        read_only_fields = ["created_at"]
