import rest_framework.serializers as serializers
import apsis.models as models


class PostSerializer(serializers.ModelSerializer):
    author = serializers.PrimaryKeyRelatedField(read_only=True)
    files = serializers.JSONField(write_only=True, required=False)

    class Meta:
        model = models.Post
        fields = [
            'id',
            'files',
            'author',
            'geolocation',
            'content',
            'name',
            'created_at',
        ]
        read_only_fields = ['created_at']
